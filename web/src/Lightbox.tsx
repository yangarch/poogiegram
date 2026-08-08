/**
 * 라이트박스 — 전체 화면 감상 (§7.1).
 *
 * 화질 단계를 올리는 순서가 중요하다. 썸네일(320)은 그리드에서 이미 받아둬서
 * **즉시** 뜬다. 그 위에 프리뷰(1600)를 얹고, 원본급(display)은 **확대했을 때만**
 * 받는다. display 는 HEIC 가 아니면 원본을 그대로 내려주는데(§6.2), 스냅사진
 * 원본은 수십 MB 라 화면에 맞춰 보는 동안에는 받을 이유가 없다.
 *
 * 라이브 포토는 길게 눌러 재생한다 — 아이폰과 같은 조작이다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { assetUrl, type AssetItem } from "./api";

/** 이 배율을 넘어가면 프리뷰가 뭉개지기 시작한다 */
const ESCALATE_AT = 1.2;
const MAX_SCALE = 6;
/** 길게 누름 판정. 짧으면 그냥 탭에도 재생돼 성가시다 */
const LONG_PRESS_MS = 350;
/** 이만큼 끌면 넘김. 화면 폭 기준이 아니라 고정값이어야 손 감각이 일정하다 */
const SWIPE_PX = 70;

interface Props {
  items: AssetItem[];
  index: number;
  onIndex: (next: number) => void;
  onClose: () => void;
}

interface Transform {
  scale: number;
  x: number;
  y: number;
}

const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${time}`;
}

export function Lightbox({ items, index, onIndex, onClose }: Props) {
  const item = items[index];
  const [transform, setTransform] = useState<Transform>(IDENTITY);
  const [hiLoaded, setHiLoaded] = useState(false);
  const [wantFull, setWantFull] = useState(false);
  const [playingMotion, setPlayingMotion] = useState(false);

  const zoomed = transform.scale > 1.01;

  // 사진이 바뀌면 확대·재생 상태를 초기화한다. 남겨두면 다음 사진이 엉뚱하게
  // 확대된 채로 열린다.
  useEffect(() => {
    setTransform(IDENTITY);
    setHiLoaded(false);
    setWantFull(false);
    setPlayingMotion(false);
  }, [item?.id]);

  useEffect(() => {
    if (transform.scale >= ESCALATE_AT) setWantFull(true);
  }, [transform.scale]);

  const go = useCallback(
    (delta: number) => {
      const next = index + delta;
      if (next >= 0 && next < items.length) onIndex(next);
    },
    [index, items.length, onIndex],
  );

  // ── 키보드 ────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // 확대 중이면 먼저 원래 크기로. 바로 닫으면 확대만 풀고 싶을 때 답답하다.
        if (zoomed) setTransform(IDENTITY);
        else onClose();
      } else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === " ") {
        e.preventDefault();
        setTransform((t) => (t.scale > 1.01 ? IDENTITY : { scale: 2.5, x: 0, y: 0 }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose, zoomed]);

  // 이웃 사진을 미리 받아둔다. 넘길 때마다 흰 화면을 보지 않으려면 필요하다.
  useEffect(() => {
    for (const neighbor of [items[index + 1], items[index - 1]]) {
      if (neighbor?.ready) new Image().src = assetUrl.preview(neighbor.id);
    }
  }, [items, index]);

  // ── 포인터 조작 ───────────────────────────────────────────────
  const surface = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const pinch = useRef<{ distance: number; scale: number } | null>(null);
  const longPress = useRef<number | null>(null);

  const cancelLongPress = () => {
    if (longPress.current !== null) {
      window.clearTimeout(longPress.current);
      longPress.current = null;
    }
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y, moved: false };

    if (item?.has_motion && !zoomed) {
      longPress.current = window.setTimeout(() => setPlayingMotion(true), LONG_PRESS_MS);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) > 6 || Math.abs(dy) > 6) {
      d.moved = true;
      cancelLongPress();
    }
    // 확대 상태에서만 끌어서 이동한다. 아니면 넘김 제스처로 해석해야 한다.
    if (zoomed) setTransform((t) => ({ ...t, x: d.tx + dx, y: d.ty + dy }));
  };

  const onPointerUp = (e: React.PointerEvent) => {
    cancelLongPress();
    if (playingMotion) setPlayingMotion(false);

    const d = drag.current;
    drag.current = null;
    if (!d || zoomed) return;

    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(dy)) {
      go(dx < 0 ? 1 : -1);
    } else if (dy > SWIPE_PX * 2) {
      onClose(); // 아래로 크게 끌면 닫기
    }
  };

  // 휠 확대. 커서 위치를 기준으로 잡아야 "보던 곳"이 유지된다.
  //
  // React 의 onWheel 은 passive 리스너로 붙어 preventDefault 가 무시된다.
  // 그대로 두면 확대하는 동안 뒤 타임라인이 같이 스크롤된다. 직접 붙인다.
  useEffect(() => {
    const el = surface.current;
    if (!el) return;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;

      setTransform((t) => {
        const next = Math.min(MAX_SCALE, Math.max(1, t.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
        if (next <= 1.01) return IDENTITY;
        const ratio = next / t.scale;
        return { scale: next, x: cx - (cx - t.x) * ratio, y: cy - (cy - t.y) * ratio };
      });
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // 두 손가락 확대
  const onTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length !== 2) return;
    cancelLongPress();
    const [a, b] = [e.touches[0], e.touches[1]];
    const distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);

    if (pinch.current === null) {
      pinch.current = { distance, scale: transform.scale };
      return;
    }
    const next = Math.min(
      MAX_SCALE,
      Math.max(1, (pinch.current.scale * distance) / pinch.current.distance),
    );
    setTransform((t) => (next <= 1.01 ? IDENTITY : { ...t, scale: next }));
  };

  if (!item) return null;

  const hiSrc = wantFull ? assetUrl.display(item.id) : assetUrl.preview(item.id);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="사진 보기">
      <div
        className="lb-surface"
        ref={surface}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onTouchMove={onTouchMove}
        onTouchEnd={() => (pinch.current = null)}
        onDoubleClick={() =>
          setTransform((t) => (t.scale > 1.01 ? IDENTITY : { scale: 2.5, x: 0, y: 0 }))
        }
        style={{ cursor: zoomed ? "grab" : "auto" }}
      >
        <div
          className="lb-stage"
          style={{
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
            // 확대 중에는 전환 애니메이션을 끈다 — 끌 때 손가락을 따라오지 않으면 답답하다
            transition: drag.current || pinch.current ? "none" : "transform 180ms ease-out",
          }}
        >
          {item.kind === "video" ? (
            <video
              className="lb-media"
              src={assetUrl.original(item.id)}
              poster={item.ready ? assetUrl.preview(item.id) : undefined}
              controls
              autoPlay
              playsInline
            />
          ) : (
            <>
              {/* 그리드에서 이미 받아둔 썸네일. 즉시 뜨므로 빈 화면을 막는다 */}
              <img className="lb-media lb-base" src={assetUrl.thumb(item.id)} alt="" aria-hidden />
              <img
                className={`lb-media lb-hi ${hiLoaded ? "loaded" : ""}`}
                src={hiSrc}
                alt=""
                onLoad={() => setHiLoaded(true)}
                draggable={false}
              />
              {playingMotion && (
                <video
                  className="lb-media lb-motion"
                  src={assetUrl.motion(item.id)}
                  autoPlay
                  muted
                  playsInline
                  onEnded={() => setPlayingMotion(false)}
                />
              )}
            </>
          )}
        </div>
      </div>

      <div className="lb-bar lb-top">
        <span className="lb-meta">
          {formatDate(item.taken_local)}
          {item.date_source === "mtime" && <em title="촬영 정보가 없어 파일 시각을 씁니다"> (추정)</em>}
        </span>
        <span className="lb-count">
          {index + 1} / {items.length}
        </span>
        <a
          className="lb-btn"
          href={assetUrl.original(item.id)}
          download
          title="원본 내려받기"
          onClick={(e) => e.stopPropagation()}
        >
          내려받기
        </a>
        <button className="lb-btn" onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </div>

      {index > 0 && (
        <button className="lb-nav lb-prev" onClick={() => go(-1)} aria-label="이전">
          ‹
        </button>
      )}
      {index < items.length - 1 && (
        <button className="lb-nav lb-next" onClick={() => go(1)} aria-label="다음">
          ›
        </button>
      )}

      {item.has_motion && !zoomed && (
        <span className="lb-hint">{playingMotion ? "LIVE 재생 중" : "길게 눌러 LIVE 재생"}</span>
      )}
    </div>
  );
}
