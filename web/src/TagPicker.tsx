/**
 * 태그 선택 (§5.5).
 *
 * 가족 사진은 사건이 계속 늘어나므로 **태그가 수백 개**가 되는 것을 전제한다.
 * 그래서 전부 늘어놓지 않고 검색이 있는 패널로 연다. 목록은 사진이 많은 순이라
 * 자주 쓰는 것이 위에 온다 — 이름순이면 매번 검색해야 한다.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TagItem } from "./api";

interface Props {
  selected: TagItem[];
  onSelect: (tags: TagItem[]) => void;
}

export function TagPicker({ selected, onSelect }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<TagItem | null>(null);
  const [draft, setDraft] = useState("");
  const [removing, setRemoving] = useState<TagItem | null>(null);
  const box = useRef<HTMLDivElement>(null);

  // 이미 있는 이름으로 바꾸면 서버가 병합한다 (§5.3). "합치기"를 따로 만들면
  // 사용자가 두 기능의 차이를 먼저 이해해야 한다.
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.renameTag(id, name),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
      // 병합되면 id 가 바뀐다. 고른 목록에도 반영해야 필터가 안 깨진다.
      onSelect(
        selected.map((s) => (s.id === editing?.id ? { ...result, count: s.count } : s)),
      );
      setEditing(null);
    },
  });

  // 태그만 지운다. 사진은 그대로다.
  //
  // 개수가 0 이어도 자동으로 지우지 않는 이유: 마지막 사진을 지우면 휴지통으로
  // 가서 개수는 0 이 되지만 asset_tag 연결은 살아 있다. 여기서 태그를 지우면
  // CASCADE 로 연결까지 사라져 **사진을 복원해도 태그가 안 돌아온다.**
  const removeTag = useMutation({
    mutationFn: (id: string) => api.deleteTag(id),
    onSuccess: (_r, id) => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
      onSelect(selected.filter((s) => s.id !== id));   // 보고 있던 태그가 사라졌다
      setRemoving(null);
    },
  });

  // 검색어는 서버로 보낸다. 태그가 수백 개면 전부 받아 거르는 것이 낭비다.
  const tags = useQuery({
    queryKey: ["tags", q],
    queryFn: () => api.tags(q),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // 여러 개를 고를 수 있다. 고른 것을 다시 누르면 해제된다 — 패널을 닫지 않는
  // 이유는 연달아 고르는 경우가 많기 때문이다.
  const toggle = (tag: TagItem) => {
    const has = selected.some((s) => s.id === tag.id);
    onSelect(has ? selected.filter((s) => s.id !== tag.id) : [...selected, tag]);
  };

  return (
    <div className="tagpicker" ref={box}>
      {/* 고른 태그는 칩으로 남긴다. 무엇을 보고 있는지 항상 보여야 한다. */}
      {selected.map((tag) => (
        <span key={tag.id} className="tag-chip">
          {tag.name}
          <button onClick={() => toggle(tag)} aria-label={`${tag.name} 해제`}>
            ✕
          </button>
        </span>
      ))}
      <button className="link" onClick={() => setOpen((v) => !v)}>
        {selected.length ? "+" : "태그 ▾"}
      </button>
      {selected.length > 1 && (
        <span className="tag-and" title="고른 태그가 모두 붙은 사진만 보입니다">
          모두 포함
        </span>
      )}

      {open && (
        <div className="tag-panel">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="태그 검색"
            aria-label="태그 검색"
          />
          <div className="tag-list">
            {tags.isPending && <p className="tag-empty">불러오는 중…</p>}
            {tags.data?.items.length === 0 && (
              <p className="tag-empty">
                {q ? "일치하는 태그가 없습니다" : "아직 태그가 없습니다"}
              </p>
            )}
            {tags.data?.items.map((tag) =>
              editing?.id === tag.id ? (
                <form
                  key={tag.id}
                  className="tag-row tag-edit"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const name = draft.trim();
                    if (name && name !== tag.name) rename.mutate({ id: tag.id, name });
                    else setEditing(null);
                  }}
                >
                  <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                    aria-label="태그 이름"
                  />
                  <button type="submit" disabled={rename.isPending}>
                    저장
                  </button>
                </form>
              ) : removing?.id === tag.id ? (
                <div key={tag.id} className="tag-row tag-confirm">
                  <span className="tag-name">
                    {tag.count > 0 ? `${tag.count}장에서 떼고 삭제?` : "태그 삭제?"}
                  </span>
                  <button
                    className="tag-yes"
                    onClick={() => removeTag.mutate(tag.id)}
                    disabled={removeTag.isPending}
                  >
                    삭제
                  </button>
                  <button className="tag-no" onClick={() => setRemoving(null)}>
                    취소
                  </button>
                </div>
              ) : (
                <div
                  key={tag.id}
                  className="tag-row"
                  data-on={selected.some((s) => s.id === tag.id)}
                >
                  <button className="tag-name" onClick={() => toggle(tag)}>
                    {selected.some((s) => s.id === tag.id) ? "✓ " : ""}
                    {tag.name}
                  </button>
                  <span className="tag-count">{tag.count}</span>
                  <button
                    className="tag-act"
                    title="이름 변경 (같은 이름으로 바꾸면 합쳐집니다)"
                    onClick={() => {
                      setEditing(tag);
                      setDraft(tag.name);
                    }}
                  >
                    ✎
                  </button>
                  {/* 사진은 지우지 않는다 — 이름표만 없앤다 */}
                  <button className="tag-act" title="태그 삭제 (사진은 남습니다)"
                    onClick={() => setRemoving(tag)}>
                    ✕
                  </button>
                </div>
              ),
            )}
          </div>
          {!q && (
            <p className="tag-hint">
              올릴 때 폴더에 넣어두면 폴더 이름이 태그가 됩니다
            </p>
          )}
        </div>
      )}
    </div>
  );
}
