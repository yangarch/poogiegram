/**
 * 사진 한 장의 태그를 보고 붙이고 떼는 줄 (§5.3).
 *
 * 이게 없으면 **사진에 뭐가 붙어 있는지 볼 방법이 없다.** 태그를 떼려면 그 태그로
 * 필터를 걸고 들어가야 했는데, 태그가 늘면 어느 것이 붙어 있는지 몰라 하나씩
 * 눌러보게 된다.
 *
 * 라이트박스에서 한 장씩 훑으며 태깅하는 것이 §5.3 이 말한 "마우스 왕복이 가장 큰
 * 마찰"에 대한 답이기도 하다.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AssetItem } from "./api";

interface Props {
  item: AssetItem;
  /** 바뀐 태그를 목록 캐시에 반영한다 — 전체를 다시 불러오면 스크롤이 튄다 */
  onChanged: (assetId: string, tags: AssetItem["tags"]) => void;
}

export function TagEditor({ item, onChanged }: Props) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const suggestions = useQuery({
    queryKey: ["tags", name],
    queryFn: () => api.tags(name),
    enabled: adding,
  });

  const after = () => {
    qc.invalidateQueries({ queryKey: ["tags"] });
    setName("");
    setAdding(false);
  };

  const add = useMutation({
    mutationFn: (tagName: string) => api.editTags([item.id], [tagName], []),
    onSuccess: async (_r, tagName) => {
      // 서버가 만든 id 를 모르므로 목록에서 찾아 붙인다. 못 찾으면 이름만으로
      // 임시 표시하고, 다음 조회에서 정확한 값으로 대체된다.
      const list = await api.tags(tagName);
      const found = list.items.find((t) => t.name === tagName);
      onChanged(item.id, [...item.tags, { id: found?.id ?? tagName, name: tagName }]);
      after();
    },
  });

  const drop = useMutation({
    mutationFn: (tagId: string) => api.editTags([item.id], [], [tagId]),
    onSuccess: (_r, tagId) => {
      onChanged(item.id, item.tags.filter((t) => t.id !== tagId));
      qc.invalidateQueries({ queryKey: ["tags"] });
    },
  });

  const typed = name.trim();
  const already = new Set(item.tags.map((t) => t.name));
  const busy = add.isPending || drop.isPending;

  return (
    <div className="lb-tags" onClick={(e) => e.stopPropagation()}>
      {item.tags.map((tag) => (
        <span key={tag.id} className="lb-tag">
          {tag.name}
          <button onClick={() => drop.mutate(tag.id)} disabled={busy} aria-label={`${tag.name} 떼기`}>
            ✕
          </button>
        </span>
      ))}

      {adding ? (
        <span className="lb-tag-add">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="태그 이름"
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter" && typed) add.mutate(typed);
              if (e.key === "Escape") {
                setName("");
                setAdding(false);
              }
            }}
          />
          {typed && (
            <div className="lb-suggest">
              {!already.has(typed) && (
                <button onClick={() => add.mutate(typed)} disabled={busy}>
                  <b>{typed}</b> 새로 만들기
                </button>
              )}
              {suggestions.data?.items
                .filter((t) => !already.has(t.name) && t.name !== typed)
                .slice(0, 5)
                .map((tag) => (
                  <button key={tag.id} onClick={() => add.mutate(tag.name)} disabled={busy}>
                    {tag.name} <span>{tag.count}</span>
                  </button>
                ))}
            </div>
          )}
        </span>
      ) : (
        <button className="lb-tag-new" onClick={() => setAdding(true)}>
          + 태그
        </button>
      )}
    </div>
  );
}
