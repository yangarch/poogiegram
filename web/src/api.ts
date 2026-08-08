/** 백엔드 호출. 세션은 httpOnly 쿠키라 JS 가 토큰을 다루지 않는다 (§8). */

export interface Me {
  id: string;
  email: string;
  display_name: string;
  role: string;
}

export interface AssetItem {
  id: string;
  kind: "image" | "video";
  /** EXIF 회전이 반영된 '화면에 보이는' 크기. 그리드가 로드 전에 자리를 잡는 데 쓴다 */
  width: number | null;
  height: number | null;
  taken_local: string;
  taken_at: string;
  duration_ms: number | null;
  is_favorite: boolean;
  has_motion: boolean;
  date_source: string;
  /** 파생물이 아직 없으면 화면에 띄울 이미지가 없다 (§6.2) */
  ready: boolean;
}

export interface AssetPage {
  items: AssetItem[];
  next_cursor: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* 본문이 JSON 이 아닐 수 있다 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("/api/auth/me"),

  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  assets: (cursor: string | null, limit = 120) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    return request<AssetPage>(`/api/assets?${params}`);
  },
};

export const assetUrl = {
  thumb: (id: string) => `/api/assets/${id}/thumb`,
  preview: (id: string) => `/api/assets/${id}/preview`,
  display: (id: string) => `/api/assets/${id}/display`,
  original: (id: string) => `/api/assets/${id}/original`,
};
