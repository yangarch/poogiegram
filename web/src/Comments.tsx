/**
 * 라이트박스의 댓글 패널 (§5.6).
 *
 * 패널을 열어 둔 채 사진을 넘기면 그 사진의 댓글로 바뀐다 — 한 장씩 훑으며
 * 읽는 것이 주된 쓰임이라, 넘길 때마다 다시 열게 하면 아무도 안 연다.
 *
 * 수정은 본인만, 삭제는 본인 + admin. 서버도 같은 규칙으로 막는다. 여기서는
 * 누를 수 없는 버튼을 보이지 않게 할 뿐이다.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CommentItem, type Me } from "./api";
import { relativeTime } from "./when";

/** 서버의 COMMENT_BODY_MAX 와 같아야 한다 */
const BODY_MAX = 1000;

export const commentsKey = (assetId: string) => ["comments", assetId] as const;

/**
 * 한글 입력 중의 Enter 는 글자 확정이지 전송이 아니다.
 * 사파리는 확정 Enter 에서 isComposing 이 이미 false 라 keyCode 229 로도 본다.
 * 이걸 빠뜨리면 마지막 글자가 잘리거나 두 번 전송된다.
 */
function isSubmitEnter(e: React.KeyboardEvent): boolean {
  return e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229;
}

interface Props {
  assetId: string;
  onClose: () => void;
}

export function Comments({ assetId, onClose }: Props) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const list = useQuery({ queryKey: commentsKey(assetId), queryFn: () => api.comments(assetId) });
  const [draft, setDraft] = useState("");

  // 목록 전체를 다시 받지 않고 캐시만 고친다. 입력하던 사람 눈앞에서 목록이
  // 깜빡이면 방금 쓴 댓글이 사라졌다 나타나는 것처럼 보인다.
  const patch = (fn: (items: CommentItem[]) => CommentItem[]) =>
    qc.setQueryData<{ items: CommentItem[] }>(commentsKey(assetId), (old) => ({
      items: fn(old?.items ?? []),
    }));

  const add = useMutation({
    mutationFn: (body: string) => api.addComment(assetId, body),
    onSuccess: (created) => {
      patch((items) => [...items, created]);
      setDraft("");
    },
  });

  const submit = () => {
    const body = draft.trim();
    if (body && !add.isPending) add.mutate(body);
  };

  const items = list.data?.items ?? [];

  return (
    <aside
      className="lb-comments"
      aria-label="댓글"
      // 라이트박스의 넘김·닫기 제스처로 새지 않게 한다
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <header className="cm-header">
        <span>댓글 {items.length > 0 && <em>{items.length}</em>}</span>
        <button className="cm-close" onClick={onClose} aria-label="댓글 닫기">
          ✕
        </button>
      </header>

      <ol className="cm-list">
        {list.isPending && <li className="cm-empty">불러오는 중…</li>}
        {list.isError && <li className="cm-empty">댓글을 불러오지 못했습니다</li>}
        {list.isSuccess && items.length === 0 && <li className="cm-empty">첫 댓글을 남겨보세요</li>}
        {items.map((c) => (
          <CommentRow key={c.id} comment={c} me={me.data} onPatch={patch} />
        ))}
      </ol>

      <div className="cm-compose">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (isSubmitEnter(e)) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="댓글 달기…"
          maxLength={BODY_MAX}
          rows={1}
          disabled={add.isPending}
        />
        <button onClick={submit} disabled={!draft.trim() || add.isPending}>
          보내기
        </button>
      </div>
      {add.isError && <p className="cm-error">{add.error.message}</p>}
    </aside>
  );
}

interface RowProps {
  comment: CommentItem;
  me: Me | undefined;
  onPatch: (fn: (items: CommentItem[]) => CommentItem[]) => void;
}

function CommentRow({ comment, me, onPatch }: RowProps) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(comment.body);
  const [confirming, setConfirming] = useState(false);

  const mine = !!me && comment.author_id === me.id;
  const canDelete = mine || me?.role === "admin";

  const save = useMutation({
    mutationFn: (body: string) => api.editComment(comment.id, body),
    onSuccess: (updated) => {
      onPatch((items) => items.map((c) => (c.id === updated.id ? updated : c)));
      setEditing(false);
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteComment(comment.id),
    onSuccess: () => onPatch((items) => items.filter((c) => c.id !== comment.id)),
  });

  const commit = () => {
    const body = text.trim();
    if (body && !save.isPending) save.mutate(body);
  };

  return (
    <li className="cm-item">
      <div className="cm-meta">
        <b>{comment.author_name ?? "알 수 없음"}</b>
        <time dateTime={comment.created_at} title={new Date(comment.created_at).toLocaleString()}>
          {relativeTime(comment.created_at)}
        </time>
        {comment.edited_at && <span className="cm-edited">수정됨</span>}
      </div>

      {editing ? (
        <div className="cm-edit">
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (isSubmitEnter(e)) {
                e.preventDefault();
                commit();
              } else if (e.key === "Escape") {
                setText(comment.body);
                setEditing(false);
              }
            }}
            maxLength={BODY_MAX}
            disabled={save.isPending}
          />
          <div className="cm-actions">
            <button onClick={commit} disabled={!text.trim() || save.isPending}>
              저장
            </button>
            <button
              onClick={() => {
                setText(comment.body);
                setEditing(false);
              }}
            >
              취소
            </button>
          </div>
        </div>
      ) : (
        <p className="cm-body">{comment.body}</p>
      )}

      {!editing && canDelete && (
        <div className="cm-actions">
          {confirming ? (
            <>
              <span>지울까요?</span>
              <button className="cm-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
                삭제
              </button>
              <button onClick={() => setConfirming(false)}>취소</button>
            </>
          ) : (
            <>
              {mine && (
                <button
                  onClick={() => {
                    setText(comment.body);
                    setEditing(true);
                  }}
                >
                  수정
                </button>
              )}
              {canDelete && <button onClick={() => setConfirming(true)}>삭제</button>}
            </>
          )}
        </div>
      )}
      {(save.isError || remove.isError) && (
        <p className="cm-error">{(save.error ?? remove.error)?.message}</p>
      )}
    </li>
  );
}
