/**
 * 태그 선택 (§5.5).
 *
 * 가족 사진은 사건이 계속 늘어나므로 **태그가 수백 개**가 되는 것을 전제한다.
 * 그래서 전부 늘어놓지 않고 검색이 있는 패널로 연다. 목록은 사진이 많은 순이라
 * 자주 쓰는 것이 위에 온다 — 이름순이면 매번 검색해야 한다.
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TagItem } from "./api";

interface Props {
  selected: TagItem | null;
  onSelect: (tag: TagItem | null) => void;
}

export function TagPicker({ selected, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);

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

  const choose = (tag: TagItem | null) => {
    onSelect(tag);
    setOpen(false);
    setQ("");
  };

  return (
    <div className="tagpicker" ref={box}>
      {selected ? (
        // 고른 태그는 칩으로 남긴다. 무엇을 보고 있는지 항상 보여야 한다.
        <span className="tag-chip">
          {selected.name}
          <button onClick={() => choose(null)} aria-label="태그 해제">
            ✕
          </button>
        </span>
      ) : (
        <button className="link" onClick={() => setOpen((v) => !v)}>
          태그 ▾
        </button>
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
            {tags.data?.items.map((tag) => (
              <button key={tag.id} className="tag-row" onClick={() => choose(tag)}>
                <span className="tag-name">{tag.name}</span>
                <span className="tag-count">{tag.count}</span>
              </button>
            ))}
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
