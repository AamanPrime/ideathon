// Lightweight client-side auth: JWT in localStorage, helpers for fetch + WS.

export type AuthUser = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  branch_code: string;
  preferred_lang: string;
};

const TOKEN_KEY = "ideathon_jwt";
const USER_KEY = "ideathon_user";

export function apiHost(): string {
  return import.meta.env.VITE_API_HOST || `${window.location.hostname}:8000`;
}

export function httpBase(): string {
  const h = apiHost();
  if (h.startsWith("http")) return h;
  return `http://${h}`;
}

export function wsUrl(path: string): string {
  const h = apiHost().replace(/^https?:\/\//, "");
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const token = getToken();
  const sep = path.includes("?") ? "&" : "?";
  return `${proto}://${h}${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ""}`;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveAuth(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const tok = getToken();
  if (tok) headers.set("Authorization", `Bearer ${tok}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(`${httpBase()}${path}`, { ...init, headers });
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${httpBase()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Login failed (${res.status})`);
  }
  const data = (await res.json()) as { access_token: string; user: AuthUser };
  saveAuth(data.access_token, data.user);
  return data.user;
}

export async function fetchMe(): Promise<AuthUser | null> {
  const tok = getToken();
  if (!tok) return null;
  const res = await apiFetch("/auth/me");
  if (!res.ok) return null;
  return (await res.json()) as AuthUser;
}
