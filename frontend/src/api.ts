/* Poka API client. Same-origin (/api) works for both Vite dev
   (proxied to :8000) and single-server mode (uvicorn serves dist). */

export interface ChatMessage {
  role: string;
  content: string;
  time?: string;
  attachments?: { id: string; kind: string; name: string }[];
  artifacts?: { id: string; kind: string; name: string }[];
  sources?: { title: string; url: string; domain: string }[];
  tools?: string[];
  model?: string;
  mode?: string;
  searched?: boolean;
  search_executed?: boolean;
}

export interface SendResult {
  message: ChatMessage;
  active_tier: string;
  task_type: string;
  warnings: string[];
}

/* API origin. Empty = same origin (local dev via Vite proxy, or
   single-server mode). Set VITE_API_URL in the hosting dashboard
   when the UI and API live on different hosts — never hardcoded. */
export const API_BASE: string =
  (import.meta.env.VITE_API_URL as string | undefined) || "";

export const apiUrl = (path: string): string => `${API_BASE}${path}`;

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("poka_token") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => req<{ ok: boolean; tiers: string[]; auth_mode: string }>("/api/health"),
  tiers: () => req<{ tiers: string[] }>("/api/tiers"),

  getChats: () => req<{ chats: any[]; current: ChatMessage[] }>("/api/chats"),
  newChat: (project_id?: string | null, chat_id?: string | null) =>
    req<{ chats: any[]; current: ChatMessage[] }>("/api/chats/new", {
      method: "POST",
      body: JSON.stringify({ project_id: project_id || null, chat_id: chat_id || null }),
    }),
  openChat: (id: string) =>
    req<{ chats: any[]; current: ChatMessage[] }>("/api/chats/open", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  renameChat: (id: string, title: string) =>
    req<{ chats: any[]; current: ChatMessage[] }>(`/api/chats/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteChat: (id: string) =>
    req<{ chats: any[]; current: ChatMessage[] }>(`/api/chats/${id}`, { method: "DELETE" }),
  clearCurrent: () =>
    req<{ chats: any[]; current: ChatMessage[] }>("/api/chats", { method: "DELETE" }),
  truncate: (index: number) =>
    req<{ chats: any[]; current: ChatMessage[] }>("/api/chats/truncate", {
      method: "POST",
      body: JSON.stringify({ index }),
    }),

  regenerate: (body: {
    index: number;
    project_id?: string | null;
    deep_mode?: boolean;
    force_search?: boolean;
    active_tier?: string | null;
  }) => req<SendResult>("/api/chat/regenerate", { method: "POST", body: JSON.stringify(body) }),

  send: (body: {
    content: string;
    upload_ids?: string[];
    project_id?: string | null;
    deep_mode?: boolean;
    force_search?: boolean;
    active_tier?: string | null;
  }) =>
    req<SendResult>("/api/chat/send", { method: "POST", body: JSON.stringify(body) }),

  /** SSE stream: onToken receives cumulative text; onDone the full result. */
  stream: async (
    body: {
      content: string;
      upload_ids?: string[];
      project_id?: string | null;
      deep_mode?: boolean;
      force_search?: boolean;
      active_tier?: string | null;
    },
    onToken: (cumulative: string) => void,
    signal?: AbortSignal,
  ): Promise<SendResult> => {
    const res = await fetch(apiUrl("/api/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok || !res.body) throw new Error("Stream failed: " + res.statusText);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result: SendResult | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data: ")) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === "token") onToken(evt.text);
        else if (evt.type === "done") result = evt.result as SendResult;
        else if (evt.type === "error") throw new Error(evt.detail || "Stream error");
      }
    }
    if (!result) throw new Error("Stream ended without a result.");
    return result;
  },

  upload: async (file: File): Promise<{ id: string; kind: string; name: string }> => {    const form = new FormData();
    form.append("file", file);
    const res = await fetch(apiUrl("/api/uploads"), {
      method: "POST",
      headers: { ...authHeaders() },
      body: form,
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Upload rejected.");
    return await res.json();
  },

  uploads: () => req<{ id: string; kind: string; name: string }[]>("/api/uploads"),

  artifacts: () => req<{ id: string; kind: string; name: string }[]>("/api/artifacts"),
  artifactUrl: (id: string) => apiUrl(`/api/artifacts/${id}/download`),
  regenerateArtifact: (id: string) =>
    req<{ id: string; kind: string; name: string }>(`/api/artifacts/${id}/regenerate`, {
      method: "POST",
    }),
  deleteArtifact: (id: string) =>
    req<{ ok: boolean }>(`/api/artifacts/${id}`, { method: "DELETE" }),
  deleteAllArtifacts: () => req<{ ok: boolean; deleted: number }>("/api/artifacts", { method: "DELETE" }),

  projects: () => req<any[]>("/api/projects"),
  createProject: (name: string) =>
    req<any>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  renameProject: (id: string, name: string) =>
    req<{ ok: boolean }>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  archiveProject: (id: string) =>
    req<{ ok: boolean }>(`/api/projects/${id}/archive`, { method: "POST" }),
  projectContext: (id: string) => req<{ text: string }>(`/api/projects/${id}/context`),
  saveProjectContext: (id: string, text: string) =>
    req<{ ok: boolean }>(`/api/projects/${id}/context`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),

  briefs: () => req<any[]>("/api/briefs"),
  saveBrief: (index: number, project_id?: string | null) =>
    req<any>("/api/briefs", {
      method: "POST",
      body: JSON.stringify({ index, project_id: project_id || null }),
    }),
  briefDocx: (id: string) =>
    req<{ id: string; kind: string; name: string }>(`/api/briefs/${id}/docx`, {
      method: "POST",
    }),
  deleteBrief: (id: string) =>
    req<{ ok: boolean }>(`/api/briefs/${id}`, { method: "DELETE" }),

  notes: () => req<{ text: string }>("/api/memory/notes"),
  saveNotes: (text: string) =>
    req<{ ok: boolean }>("/api/memory/notes", {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),
  facts: () => req<any[]>("/api/memory/facts"),
  deleteFact: (ref: string) =>
    req<{ ok: boolean }>("/api/memory/facts", {
      method: "DELETE",
      body: JSON.stringify({ ref }),
    }),
};
