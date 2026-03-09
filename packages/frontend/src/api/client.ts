/**
 * API client — typed fetch wrapper for the backend.
 *
 * Learn: Centralized API client with base URL handling, error parsing,
 * and JWT auth token injection. All API calls go through here.
 *
 * In development, Vite's proxy forwards /api/* to http://localhost:8000.
 * In production, the frontend is served by the backend or a CDN.
 */

const BASE_URL = import.meta.env.VITE_API_URL || "";
const TOKEN_KEY = "openclaw_token";

// ─── Token helpers ──────────────────────────────────────

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// ─── API Client ─────────────────────────────────────────

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const url = new URL(path, this.baseUrl || window.location.origin);
    if (params) {
      Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    }
    const resp = await fetch(url.toString(), {
      headers: this.headers(),
    });
    if (!resp.ok) throw await this.parseError(resp);
    return resp.json();
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) throw await this.parseError(resp);
    return resp.json();
  }

  async patch<T>(path: string, body: unknown): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "PATCH",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw await this.parseError(resp);
    return resp.json();
  }

  async delete(path: string): Promise<void> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: "DELETE",
      headers: this.headers(),
    });
    if (!resp.ok) throw await this.parseError(resp);
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = getToken();
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  }

  private async parseError(resp: Response): Promise<Error> {
    try {
      const data = await resp.json();
      return new Error(data.detail || resp.statusText);
    } catch {
      return new Error(resp.statusText);
    }
  }
}

export const apiClient = new ApiClient(BASE_URL);
