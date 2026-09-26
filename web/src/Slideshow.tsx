/**
 * 슬라이드 쇼 — 액자 모드 (§7.2).
 *
 * 골라둔 사진을 전체화면에서 무작위로 돌린다. 기준은 "앉아서 넘겨보는 슬라이드 쇼"가
 * 아니라 **틀어두고 지나가며 보는 액자**다. 그 전제가 설계를 몇 군데 바꾼다.
 *
 * - **기본 간격이 1분이다.** 짧으면 지나가며 볼 때 산만하다.
 * - **`preview`(1600)만 쓴다.** `display`는 원본을 그대로 내려주기도 해서(§6.2) 수십
 *   MB인데, 몇 시간을 틀어두면 외장 HDD와 회선을 계속 헛돈다.
 * - **Wake Lock 이 없으면 기능이 성립하지 않는다.** 1분 간격이면 태블릿은 두 장 넘기고
 *   잠든다. 보안 컨텍스트(HTTPS·localhost)에서만 동작하므로 LAN 평문 접속에서는
 *   못 잡는다 — 그때는 화면이 꺼질 수 있다고 알린다.
 * - **움직이는 것은 전부 CSS 로 돌린다.** 몇 시간 켜두는 화면에서 매 프레임 setState 하면
 *   배터리가 남지 않는다. 남은 시간 표시까지 애니메이션이라 JS 타이머는 넘길 때 하나뿐이다.
 * - **영상은 대상에서 뺀다** — 1분 간격과 3분짜리 영상은 서로 맞지 않는다. 라이브 포토는
 *   정지컷으로 들어온 뒤 모션 클립을 한 번만 재생한다(아이폰과 같은 인상).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { assetUrl, type AssetItem } from "./api";
import { advance, back, start } from "./shuffle";

const INTERVALS = [
  { label: "15초", ms: 15_000 },
  { label: "1분", ms: 60_000 },
  { label: "5분", ms: 300_000 },
];
const DEFAULT_MS = 60_000;

/** 크로스페이드 길이. 액자에서는 넉넉해야 "넘어갔다"가 아니라 "바뀌어 있다"가 된다 */
const FADE_MS = 1200;
/** 모션 클립은 사진이 자리를 잡은 뒤에 재생한다. 페이드 도중에 움직이면 어수선하다 */
const MOTION_DELAY_MS = 800;
/** 손을 놓으면 조작 UI 를 감춘다 — 액자에 버튼이 떠 있으면 사진이 아니라 앱이 된다 */
const IDLE_MS = 2600;

/** 한 장을 화면에 올릴 때 필요한 것 전부. 빠질 때도 같은 값으로 그려야 한다 */
interface Shot {
  item: AssetItem;
  /** 켄번즈 방향. 번갈아 줘야 계속 같은 방향으로만 당기지 않는다 */
  kb: "in" | "out";
  ms: number;
}

interface Props {
  /** 대상 후보. 영상·미변환은 여기서 걸러낸다 */
  items: AssetItem[];
  onClose: () => void;
}

export function Slideshow({ items, onClose }: Props) {
  // 열 때 한 번 붙잡는다. 무한 스크롤로 계속 늘어나는 배열을 그대로 쓰면 페이지가
  // 도착할 때마다 순서가 다시 섞여 방금 본 사진이 또 나온다.
  //
  // 파생물이 없는 것(ready=false)은 띄울 이미지가 없어 한 간격 내내 빈 화면이 된다.
  const [pool] = useState(() => items.filter((i) => i.ready && i.kind === "image"));
  const ids = useMemo(() => pool.map((i) => i.id), [pool]);
  const byId = useMemo(() => new Map(pool.map((i) => [i.id, i])), [pool]);

  const [queue, setQueue] = useState(() => start(ids));
  const [intervalMs, setIntervalMs] = useState(DEFAULT_MS);
  const [paused, setPaused] = useState(false);
  /** 페이드로 빠지는 중인 앞 사진. 새 사진이 이 위에 덮인다 */
  const [leaving, setLeaving] = useState<Shot | null>(null);
  const [motionOn, setMotionOn] = useState(false);
  const [ui, setUi] = useState(false);
  const [noWakeLock, setNoWakeLock] = useState(false);

  const item = byId.get(queue.order[queue.cursor]) ?? null;
  const upcoming = byId.get(queue.order[queue.cursor + 1]) ?? null;
  const shot: Shot | null = item
    ? { item, kb: queue.cursor % 2 === 0 ? "in" : "out", ms: intervalMs }
    : null;

  const go = useCallback(
    (delta: 1 | -1) => {
      if (shot) setLeaving(shot);
      setQueue((q) => (delta === 1 ? advance(q, ids) : back(q)));
    },
    [shot, ids],
  );

  // ── 넘기기 ────────────────────────────────────────────────────
  //
  // 남은 시간을 ref 에 들고 있다. 일시정지에서 풀 때 처음부터 다시 세면 진행 막대(CSS
  // 애니메이션은 멈춘 자리에서 이어진다)와 어긋나서, 막대가 거의 다 찼는데 1분을 더
  // 기다리게 된다.
  const remaining = useRef(intervalMs);

  // 사진이나 간격이 바뀌면 처음부터 센다. **아래 타이머보다 먼저 선언해야 한다** —
  // 정리(cleanup)가 먼저 돌고 그다음 효과가 선언 순서대로 돌기 때문이다.
  useEffect(() => {
    remaining.current = intervalMs;
  }, [item, intervalMs]);

  useEffect(() => {
    if (paused || !item) return;
    const wait = remaining.current;
    const startedAt = Date.now();
    const id = window.setTimeout(() => go(1), wait);
    return () => {
      window.clearTimeout(id);
      remaining.current = Math.max(0, wait - (Date.now() - startedAt));
    };
  }, [paused, item, intervalMs, go]);

  // 다음 장을 미리 받아둔다. 순서가 정해져 있으니 1분이면 넉넉하다.
  useEffect(() => {
    if (upcoming) new Image().src = assetUrl.preview(upcoming.id);
  }, [upcoming]);

  // 라이브 포토의 모션 재생. 일시정지는 보지 않는다 — 넣으면 풀 때마다 다시 재생된다.
  useEffect(() => {
    setMotionOn(false);
    if (!item?.has_motion) return;
    const id = window.setTimeout(() => setMotionOn(true), MOTION_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [item]);

  // ── 화면 꺼짐 방지 ────────────────────────────────────────────
  useEffect(() => {
    const nav = navigator as Navigator & {
      wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> };
    };
    if (!nav.wakeLock) {
      setNoWakeLock(true);
      return;
    }

    let sentinel: { release: () => Promise<void> } | null = null;
    let done = false;

    const acquire = async () => {
      try {
        const next = await nav.wakeLock!.request("screen");
        // 기다리는 동안 닫혔으면 바로 놓아준다 — 안 그러면 그 뒤로 화면이 안 꺼진다
        if (done) void next.release();
        else sentinel = next;
      } catch {
        setNoWakeLock(true); // 평문 접속이거나 브라우저가 거부했다
      }
    };
    void acquire();

    // 탭이 뒤로 가면 브라우저가 잠금을 풀어버린다. 돌아왔을 때 다시 잡지 않으면
    // 그 뒤로는 화면이 꺼진다.
    const onVisible = () => {
      if (document.visibilityState === "visible" && !sentinel && !done) void acquire();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      done = true;
      document.removeEventListener("visibilitychange", onVisible);
      void sentinel?.release();
    };
  }, []);

  // ── 조작 UI 감추기 ────────────────────────────────────────────
  const idle = useRef<number | null>(null);
  const reveal = useCallback(() => {
    setUi(true);
    if (idle.current !== null) window.clearTimeout(idle.current);
    idle.current = window.setTimeout(() => setUi(false), IDLE_MS);
  }, []);

  // 시작할 때 한 번 보여준다. 간격을 바꾸는 버튼이 여기 있다는 것을 알려야 한다.
  useEffect(() => {
    reveal();
    return () => {
      if (idle.current !== null) window.clearTimeout(idle.current);
    };
  }, [reveal]);

  // ── 전체화면 ──────────────────────────────────────────────────
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // 아이폰 사파리에는 요소 전체화면이 없다. 실패해도 이 오버레이가 화면을 다
    // 덮으므로 그대로 간다.
    void rootRef.current?.requestFullscreen?.({ navigationUI: "hide" }).catch(() => {});
    return () => {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    };
  }, []);

  // F11·Esc 로 전체화면을 빠져나가면 슬라이드 쇼도 끝낸다. 전체화면만 풀리고 남으면
  // 타임라인 위에 검은 판이 덮여 있는 셈이다.
  useEffect(() => {
    let entered = false;
    const onChange = () => {
      if (document.fullscreenElement) entered = true;
      else if (entered) onClose();
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === " ") {
        // 버튼에 포커스가 남아 있으면 Space 는 그 버튼의 것이다. 여기서 또 처리하면
        // 일시정지가 두 번 토글돼 제자리로 돌아온다.
        if (e.target instanceof HTMLButtonElement) return;
        e.preventDefault();
        setPaused((p) => !p);
      } else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else return; // 그 밖의 키로는 UI 를 깨우지 않는다
      reveal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose, reveal]);

  // 빠지는 사진과 새 사진을 **한 배열로** 그린다. 따로 두면 React 가 같은 사진을
  // 다른 자리로 보고 DOM 을 새로 만들어, 켄번즈로 확대돼 있던 것이 페이드 도중에
  // 원래 크기로 튄다. key 로 이어주면 노드가 살아남아 확대된 채로 빠진다.
  const stack: Shot[] = [];
  if (leaving && leaving.item.id !== item?.id) stack.push(leaving);
  if (shot) stack.push(shot);

  return (
    <div
      className="slideshow"
      data-ui={ui}
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-label="슬라이드 쇼"
      onPointerMove={reveal}
      onPointerDown={reveal}
    >
      {!pool.length ? (
        <div className="ss-empty">
          <p>
            슬라이드 쇼로 보여줄 사진이 없습니다.
            <br />
            영상과 아직 처리 중인 파일은 제외됩니다.
          </p>
          <button className="lb-btn" onClick={onClose}>
            닫기
          </button>
        </div>
      ) : (
        <>
          {stack.map((s) => (
            <Frame
              key={s.item.id}
              shot={s}
              entering={s.item.id === item?.id}
              paused={paused}
              // 페이드가 끝나면 앞 사진을 치운다. 놔두면 투명한 층이 계속 쌓인다.
              onEntered={() => setLeaving(null)}
              motion={s.item.id === item?.id && motionOn}
              onMotionEnded={() => setMotionOn(false)}
            />
          ))}

          {/* 날짜는 잠깐 떴다 사라진다. 액자에 글자가 박혀 있으면 사진을 방해한다 */}
          {item && (
            <div className="ss-caption" key={`cap-${item.id}`}>
              {formatDay(item.taken_local)}
            </div>
          )}

          <div className="ss-controls">
            <div
              className="ss-progress"
              // 남은 시간을 CSS 로 그린다. 사진이 바뀌면 key 로 처음부터 다시 시작한다.
              key={`p-${item?.id}-${intervalMs}`}
              style={{
                animationDuration: `${intervalMs}ms`,
                animationPlayState: paused ? "paused" : "running",
              }}
            />
            <div className="ss-bar">
              <button
                className="lb-btn"
                onClick={() => setPaused((p) => !p)}
                aria-label={paused ? "재생" : "일시정지"}
              >
                {paused ? "▶" : "❙❙"}
              </button>
              <button
                className="lb-btn"
                onClick={() => go(-1)}
                disabled={queue.cursor === 0}
                aria-label="이전"
              >
                ‹
              </button>
              <button className="lb-btn" onClick={() => go(1)} aria-label="다음">
                ›
              </button>

              <span className="ss-intervals">
                {INTERVALS.map((it) => (
                  <button
                    key={it.ms}
                    className="lb-btn"
                    data-on={it.ms === intervalMs}
                    onClick={() => setIntervalMs(it.ms)}
                  >
                    {it.label}
                  </button>
                ))}
              </span>

              <span className="spacer" />
              {noWakeLock && (
                <span className="ss-warn" title="HTTPS 접속에서만 화면 꺼짐을 막을 수 있습니다">
                  화면이 꺼질 수 있습니다
                </span>
              )}
              <span className="ss-count">{pool.length}장</span>
              <button className="lb-btn" onClick={onClose} aria-label="끝내기">
                ✕
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Frame({
  shot,
  entering,
  paused,
  onEntered,
  motion,
  onMotionEnded,
}: {
  shot: Shot;
  entering: boolean;
  paused: boolean;
  onEntered: () => void;
  motion: boolean;
  onMotionEnded: () => void;
}) {
  const { item, kb, ms } = shot;
  return (
    <div
      className={`ss-layer ${entering ? "ss-entering" : ""}`}
      style={{ animationDuration: `${FADE_MS}ms` }}
      // 자식(켄번즈·캡션)의 animationend 도 여기까지 올라온다. 이 층의 것만 본다.
      onAnimationEnd={(e) => {
        if (e.target === e.currentTarget) onEntered();
      }}
    >
      {/* 레터박스를 같은 사진의 흐린 확대로 채운다. 액자에서 검은 띠는 눈에 걸린다.
          썸네일은 그리드에서 이미 받아둬서 추가 전송이 없다. */}
      <img className="ss-backdrop" src={assetUrl.thumb(item.id)} alt="" aria-hidden />
      <img
        className={`ss-photo ss-kb-${kb}`}
        src={assetUrl.preview(item.id)}
        alt=""
        draggable={false}
        // 아주 느린 확대로 정지 화면의 답답함을 덜어낸다. 간격에 맞춰 끝난다.
        style={{ animationDuration: `${ms}ms`, animationPlayState: paused ? "paused" : "running" }}
      />
      {motion && (
        <video
          className="ss-motion"
          src={assetUrl.motion(item.id)}
          autoPlay
          muted
          playsInline
          onEnded={onMotionEnded}
          // 못 받아오면 정지컷만 남는다 — 슬라이드 쇼를 멈출 이유는 아니다
          onError={onMotionEnded}
        />
      )}
    </div>
  );
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
}
