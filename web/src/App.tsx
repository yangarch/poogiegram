import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type TagItem } from "./api";
import { Login } from "./Login";
import { TagPicker } from "./TagPicker";
import { Timeline } from "./Timeline";
import { Upload } from "./Upload";

export function App() {
  const qc = useQueryClient();
  const [tag, setTag] = useState<TagItem | null>(null);
  const [uploading, setUploading] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    // 로그인하지 않은 상태는 오류가 아니라 정상 경로다. 재시도하지 않는다.
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => qc.clear(),
  });

  if (me.isPending) return <div className="notice">…</div>;
  if (me.isError) return <Login />;

  return (
    <div className="app">
      <header className="topbar">
        <strong>poogiegram</strong>
        <TagPicker selected={tag} onSelect={setTag} />
        <span className="spacer" />
        <button className="link" onClick={() => setSelectMode((v) => !v)}>
          {selectMode ? "선택 끝내기" : "선택"}
        </button>
        <button className="link" onClick={() => setUploading(true)}>
          올리기
        </button>
        <span className="who">{me.data.display_name}</span>
        <button className="link" onClick={() => logout.mutate()}>
          로그아웃
        </button>
      </header>
      <Timeline
        tag={tag}
        selectMode={selectMode}
        onExitSelect={() => setSelectMode(false)}
      />
      {uploading && <Upload tag={tag} onClose={() => setUploading(false)} />}
    </div>
  );
}
