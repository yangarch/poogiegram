/**
 * 선택 중일 때 뜨는 작업 막대 (§5.3).
 *
 * 태그 입력은 **자동완성이 있어야 한다.** 없으면 `여행`/`여행지`/`trip` 으로 표기가
 * 흩어져 나중에 검색이 무의미해진다. 그래서 기존 태그를 제안하되, 목록에 없는
 * 이름도 그대로 만들 수 있게 둔다 — 새 사건은 계속 생기기 때문이다.
 */

import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TagItem } from "./api";

interface Props {
  ids: string[];
  onClear: () => void;
  /** 태그를 보고 있을 때의 "빼기" 버튼 등, 문맥에 따라 달라지는 동작 */
  children?: ReactNode;
}

export function SelectionBar({ ids, onClear, children }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState(false);

  const suggestions = useQuery({
    queryKey: ["tags", name],
    queryFn: () => api.tags(name),
  });

  const done = () => {
    qc.invalidateQueries({ queryKey: ["assets"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    onClear();
  };

  const addTag = useMutation({
    mutationFn: (tagName: string) => api.editTags(ids, [tagName], []),
    onSuccess: done,
  });

  const removeTag = useMutation({
    mutationFn: (tagId: string) => api.editTags(ids, [], [tagId]),
    onSuccess: done,
  });

  const remove = useMutation({
    mutationFn: () => api.deleteAssets(ids),
    onSuccess: done,
  });

  const busy = addTag.isPending || removeTag.isPending || remove.isPending;
  const typed = name.trim();
  // 입력한 이름이 기존 태그와 정확히 같으면 "새로 만들기"를 또 보여줄 필요가 없다
  const exact = suggestions.data?.items.find((t) => t.name === typed);

  return (
    <div className="selbar">
      <span className="selbar-count">{ids.length}장 선택</span>

      <div className="selbar-tag">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="태그 붙이기"
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && typed) addTag.mutate(typed);
          }}
        />
        {typed && (
          <div className="selbar-suggest">
            {!exact && (
              <button onClick={() => addTag.mutate(typed)} disabled={busy}>
                <b>{typed}</b> 새로 만들기
              </button>
            )}
            {suggestions.data?.items.slice(0, 6).map((tag: TagItem) => (
              <button key={tag.id} onClick={() => addTag.mutate(tag.name)} disabled={busy}>
                {tag.name} <span>{tag.count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <span className="spacer" />

      {children}

      {confirming ? (
        <>
          {/* 삭제는 되돌릴 수 있지만(휴지통) 확인은 받는다 — 선택이 여러 장이라 */}
          <span className="selbar-warn">{ids.length}장을 휴지통으로?</span>
          <button className="danger" onClick={() => remove.mutate()} disabled={busy}>
            삭제
          </button>
          <button className="link" onClick={() => setConfirming(false)}>
            취소
          </button>
        </>
      ) : (
        <button className="link" onClick={() => setConfirming(true)} disabled={busy}>
          삭제
        </button>
      )}
      <button className="link" onClick={onClear}>
        선택 해제
      </button>
    </div>
  );
}

/** 지금 보고 있는 태그를 선택한 사진들에서 떼어낸다 */
export function RemoveFromTag({
  ids,
  tag,
  onDone,
}: {
  ids: string[];
  tag: TagItem;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.editTags(ids, [], [tag.id]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      onDone();
    },
  });
  return (
    <button className="link" onClick={() => remove.mutate()} disabled={remove.isPending}>
      "{tag.name}"에서 빼기
    </button>
  );
}
