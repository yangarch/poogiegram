import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type TagItem } from "./api";
import { Login } from "./Login";
import { TagPicker } from "./TagPicker";
import { Timeline } from "./Timeline";
import { Upload } from "./Upload";

export function App() {
  const qc = useQueryClient();
  const [tags, setTags] = useState<TagItem[]>([]);
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
        <TagPicker selected={tags} onSelect={setTags} />
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
      {/* 선택 모드 종료는 헤더에서만 한다. 막대의 "선택 해제"는 고른 것만 비운다 */}
      <Timeline tags={tags} selectMode={selectMode} />
      {uploading && <Upload tags={tags} onClose={() => setUploading(false)} />}
    </div>
  );
}
