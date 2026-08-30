/**
 * 선택 중일 때 뜨는 작업 막대 (§5.3).
 *
 * 태그 입력은 **자동완성이 있어야 한다.** 없으면 `여행`/`여행지`/`trip` 으로 표기가
 * 흩어져 나중에 검색이 무의미해진다. 그래서 기존 태그를 제안하되, 목록에 없는
 * 이름도 그대로 만들 수 있게 둔다 — 새 사건은 계속 생기기 때문이다.
 *
 * **태그를 붙여도 선택은 유지한다.** 하나 붙일 때마다 선택이 풀리면 두 번째 태그를
 * 붙이려고 처음부터 다시 골라야 한다. 사진이 사라지는 동작(삭제·현재 태그에서 빼기)
 * 에서만 선택을 비운다.
 */

import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TagItem } from "./api";

interface Props {
  ids: string[];
  /** 지금까지 불러온 사진 수. 무한 스크롤이라 "모두"는 여기까지다 */
  loaded: number;
  onSelectAll: () => void;
  /** 선택만 비운다. 선택 모드는 유지된다 — 모드 종료는 헤더에서 한다 */
  onClear: () => void;
  /** 태그를 보고 있을 때의 "빼기" 버튼 등, 문맥에 따라 달라지는 동작 */
  children?: ReactNode;
}

/** 쉼표로 여러 개를 한 번에. 업로드와 같은 규칙이다 (§5.5) */
export function parseTags(raw: string): string[] {
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

export function SelectionBar({ ids, loaded, onSelectAll, onClear, children }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [justAdded, setJustAdded] = useState<string[]>([]);

  // 쉼표로 나눠 입력하는 중이면 마지막 조각으로 제안한다
  const fragment = name.split(",").pop()?.trim() ?? "";
  const suggestions = useQuery({
    queryKey: ["tags", fragment],
    queryFn: () => api.tags(fragment),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["assets"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
  };

  const addTag = useMutation({
    mutationFn: (names: string[]) => api.editTags(ids, names, []),
    onSuccess: (_result, names) => {
      refresh();
      setName("");
      // 선택이 그대로라 화면이 거의 변하지 않는다. 무엇이 붙었는지 잠깐 알린다.
      setJustAdded(names);
      window.setTimeout(() => setJustAdded([]), 2400);
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteAssets(ids),
    onSuccess: () => {
      refresh();
      onClear();   // 사진이 목록에서 사라졌다 — 고른 채로 두면 다음 동작이 헛돈다
      setConfirming(false);
    },
  });

  const busy = !ids.length || addTag.isPending || remove.isPending;
  const parsed = parseTags(name);
  // 입력한 이름이 기존 태그와 정확히 같으면 "새로 만들기"를 또 보여줄 필요가 없다
  const exact = suggestions.data?.items.find((t) => t.name === fragment);

  return (
    <div className="selbar">
      <span className="selbar-count">
        {ids.length ? `${ids.length}장 선택` : "사진을 고르세요"}
      </span>
      {ids.length < loaded && (
        <button className="link" onClick={onSelectAll}>
          모두 선택 ({loaded})
        </button>
      )}

      <div className="selbar-tag">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="태그 붙이기 (쉼표로 여러 개)"
          disabled={busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && parsed.length) addTag.mutate(parsed);
          }}
        />
        {fragment && (
          <div className="selbar-suggest">
            {parsed.length > 1 ? (
              <button onClick={() => addTag.mutate(parsed)} disabled={busy}>
                <b>{parsed.join(", ")}</b> — {parsed.length}개 붙이기
              </button>
            ) : (
              <>
                {!exact && (
                  <button onClick={() => addTag.mutate([fragment])} disabled={busy}>
                    <b>{fragment}</b> 새로 만들기
                  </button>
                )}
                {suggestions.data?.items.slice(0, 6).map((tag: TagItem) => (
                  <button key={tag.id} onClick={() => addTag.mutate([tag.name])} disabled={busy}>
                    {tag.name} <span>{tag.count}</span>
                  </button>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {justAdded.length > 0 && <span className="selbar-ok">{justAdded.join(", ")} 붙임</span>}

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
      <button className="link" onClick={onClear} disabled={!ids.length}>
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
      // 이 태그로 거르는 중이라 사진이 목록에서 빠진다 — 선택을 비운다
      onDone();
    },
  });
  return (
    <button className="link" onClick={() => remove.mutate()} disabled={!ids.length || remove.isPending}>
      "{tag.name}"에서 빼기
    </button>
  );
}
