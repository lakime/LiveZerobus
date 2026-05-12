async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

export type SapTable = {
  name: string;
  description: string;
  module: string;
  row_count: number;
  available: boolean;
};

export type TableData = {
  total: number;
  offset: number;
  limit: number;
  columns: string[];
  rows: string[][];
};

export type ServiceInfo = {
  share: string;
  schema: string;
  endpoint: string;
  host: string;
  tables_ready: number;
  tables_total: number;
  tables_shared: number;
};

export type RegenerateResult = {
  ok: boolean;
  tables: { name: string; rows: number }[];
};

export type SharingEntry = {
  name: string;
  enabled: boolean;
};

export type SharingStatus = {
  tables: SharingEntry[];
  enabled_count: number;
  total_count: number;
};

export const api = {
  tables: () => get<SapTable[]>("/api/tables"),

  tableRows: (name: string, offset = 0, limit = 50, q = "") =>
    get<TableData>(`/api/tables/${name}/rows?offset=${offset}&limit=${limit}&q=${encodeURIComponent(q)}`),

  info: () => get<ServiceInfo>("/api/info"),

  regenerate: () => post<RegenerateResult>("/api/regenerate"),

  downloadProfile: () => {
    const a = document.createElement("a");
    a.href = "/api/profile.json";
    a.download = "sap-bdc-profile.json";
    a.click();
  },

  sharingStatus: () => get<SharingStatus>("/api/sharing"),
  setSharing: (name: string, enabled: boolean) =>
    post<SharingEntry>(`/api/sharing/${encodeURIComponent(name)}`, { enabled }),
  enableAll: () => post<{ enabled: string[] }>("/api/sharing/enable-all"),
  disableAll: () => post<{ enabled: string[] }>("/api/sharing/disable-all"),
};
