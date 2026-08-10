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

export interface TagItem {
  id: string;
  name: string;
  /** 이 태그로 열리는 사진 수. 빈 태그가 쌓이는 것을 눈으로 확인할 수 있어야 한다 */
  count: number;
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

  assets: (cursor: string | null, tagId: string | null = null, limit = 120) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    if (tagId) params.set("tag_id", tagId);
    return request<AssetPage>(`/api/assets?${params}`);
  },

  /**
   * 파일 하나를 올린다.
   *
   * fetch 는 업로드 진행률을 알려주지 않는다. 진행률이 없으면 큰 파일에서 멈춘
   * 건지 올라가는 중인지 구분이 안 돼 사용자가 취소해버린다. XHR 만 upload.progress
   * 를 준다.
   */
  upload: (file: File, tag: string | null, onProgress?: (ratio: number) => void) =>
    new Promise<{ filename: string; bytes: number }>((resolve, reject) => {
      const body = new FormData();
      body.append("file", file);
      if (tag) body.append("tag", tag);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.withCredentials = true;

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
          return;
        }
        let detail = `업로드 실패 (${xhr.status})`;
        try {
          const parsed = JSON.parse(xhr.responseText);
          if (typeof parsed.detail === "string") detail = parsed.detail;
        } catch {
          /* 본문이 JSON 이 아닐 수 있다 */
        }
        reject(new ApiError(xhr.status, detail));
      };
      xhr.onerror = () => reject(new ApiError(0, "연결이 끊겼습니다"));
      xhr.ontimeout = () => reject(new ApiError(0, "시간이 초과됐습니다"));
      xhr.send(body);
    }),

  tags: (q?: string) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    return request<{ items: TagItem[] }>(`/api/tags?${params}`);
  },
};

export const assetUrl = {
  thumb: (id: string) => `/api/assets/${id}/thumb`,
  preview: (id: string) => `/api/assets/${id}/preview`,
  display: (id: string) => `/api/assets/${id}/display`,
  original: (id: string) => `/api/assets/${id}/original`,
  /** 라이브 포토의 동반 클립. 정지컷 ID 로 요청한다 (§6.5) */
  motion: (id: string) => `/api/assets/${id}/motion`,
};
