/**
 * 타임라인 그리드 (§7.1).
 *
 * 여백 있는 갤러리형 — 행 높이를 크게(280px) 잡고 간격을 넉넉히 둔다.
 * 밀도형(구글 포토식)보다 한 장 한 장이 읽히는 대신 스크롤이 길어지므로,
 * 월 단위 헤더로 리듬을 준다.
 *
 * 가상 스크롤이 필수다 — 수만 장에서 DOM 을 다 그리면 브라우저가 멈춘다.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { api, assetUrl, type AssetItem } from "./api";
import { layoutRows, widthsOf, type Row } from "./layout";
import { Lightbox } from "./Lightbox";
import { RemoveFromTag, SelectionBar } from "./SelectionBar";
import { Slideshow } from "./Slideshow";
import type { TagItem } from "./api";

const GAP = 14;
const TARGET_HEIGHT = 280;
const HEADER_HEIGHT = 72;
/** 화면 밖 여유분. 스크롤할 때 빈 칸이 보이지 않을 만큼만 그린다 */
const OVERSCAN = 800;

type Block =
  | { type: "header"; key: string; label: string; top: number; height: number }
  | { type: "row"; key: string; row: Row<AssetItem>; top: number; height: number };

function monthLabel(iso: string): string {
  const [y, m] = iso.split("-");
  return `${y}년 ${Number(m)}월`;
}

/** 월 단위로 묶고, 각 묶음을 따로 배치한 뒤 세로 위치를 계산한다 */
function buildBlocks(items: AssetItem[], width: number): { blocks: Block[]; total: number } {
  const groups = new Map<string, AssetItem[]>();
  for (const item of items) {
    const key = item.taken_local.slice(0, 7); // YYYY-MM
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(item);
  }

  const blocks: Block[] = [];
  let top = 0;
  for (const [key, groupItems] of groups) {
    blocks.push({ type: "header", key: `h-${key}`, label: monthLabel(key), top, height: HEADER_HEIGHT });
    top += HEADER_HEIGHT;

    for (const [i, row] of layoutRows(groupItems, width, TARGET_HEIGHT, GAP).entries()) {
      blocks.push({ type: "row", key: `r-${key}-${i}`, row, top, height: row.height });
      top += row.height + GAP;
    }
    top += 24; // 월 사이 여백
  }
  return { blocks, total: top };
}

function Tile({
  item,
  width,
  height,
  onOpen,
  selecting,
  selected,
}: {
  item: AssetItem;
  width: number;
  height: number;
  onOpen: (mode: "toggle" | "range") => void;
  selecting: boolean;
  selected: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  // 터치에는 드래그 선택을 쓸 수 없다 — 끌기가 스크롤이라 가로채면 목록을 못
  // 내린다. 대신 길게 눌러 "여기까지" 범위 선택을 한다.
  const press = useRef<number | null>(null);
  const ranged = useRef(false);

  const cancelPress = () => {
    if (press.current !== null) {
      window.clearTimeout(press.current);
      press.current = null;
    }
  };

  return (
    <div
      className="tile"
      style={{ width, height }}
      data-ready={item.ready}
      data-selected={selected}
      onClick={(e) => {
        // 길게 눌러 범위를 잡은 뒤의 click 은 무시한다 — 안 그러면 마지막 타일이
        // 곧바로 해제된다.
        if (ranged.current) {
          ranged.current = false;
          return;
        }
        onOpen(e.shiftKey ? "range" : "toggle");
      }}
      onPointerDown={(e) => {
        if (!selecting || e.pointerType !== "touch") return;
        press.current = window.setTimeout(() => {
          ranged.current = true;
          onOpen("range");
        }, 450);
      }}
      onPointerMove={cancelPress}
      onPointerUp={cancelPress}
      onPointerCancel={cancelPress}
      // 키보드로도 열려야 한다 — 그리드 전체가 마우스 전용이 되면 곤란하다
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(e.shiftKey ? "range" : "toggle");
        }
      }}
    >
      {item.ready ? (
        <img
          src={assetUrl.thumb(item.id)}
          alt=""
          loading="lazy"
          decoding="async"
          width={width}
          height={height}
          className={loaded ? "loaded" : ""}
          onLoad={() => setLoaded(true)}
        />
      ) : (
        // 파생물이 아직 없으면 띄울 이미지가 없다. 빈 칸으로 두면 "왜 안 나오지"가 되므로
        // 처리 중임을 드러낸다 (§6.1).
        <div className="tile-pending" title="처리 중">
          <span />
        </div>
      )}
      {item.kind === "video" && <span className="badge">▶</span>}
      {item.has_motion && <span className="badge badge-motion">LIVE</span>}
      {/* 선택 모드에서만 체크를 보여준다. 항상 띄우면 감상에 방해가 된다 */}
      {selecting && <span className="tile-check">{selected ? "✓" : ""}</span>}
    </div>
  );
}

export function Timeline({
  tags,
  selectMode,
  slideshow,
  onSlideshow,
}: {
  tags: TagItem[];
  selectMode: boolean;
  slideshow: boolean;
  onSlideshow: (on: boolean) => void;
}) {
  // 쿼리 키에 그대로 쓰므로 순서가 흔들리면 안 된다 — 고른 순서가 달라도 같은
  // 조건이면 같은 캐시를 써야 한다.
  const tagIds = useMemo(() => tags.map((t) => t.id).sort(), [tags]);
  const qc = useQueryClient();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // 헤더에서 선택 모드로 들어온다. 아무것도 안 고른 상태에서도 모드가 유지돼야
  // 첫 장을 고를 수 있다 — 개수로 판단하면 진입 자체가 불가능하다.
  const selecting = selectMode;

  // 모드를 빠져나가면 선택도 비운다. 남겨두면 다시 들어왔을 때 지난 선택이 살아 있다.
  useEffect(() => {
    if (!selectMode) setSelected(new Set());
  }, [selectMode]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // ── 드래그 선택 ─────────────────────────────────────────────
  //
  // 타일 위치는 레이아웃에서 이미 계산해 두었으므로 DOM 을 재지 않는다. 덕분에
  // **화면 밖 타일도 잡힌다** — 가상 스크롤이라 DOM 에는 보이는 것만 있다.
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; base: Set<string>; moved: boolean } | null>(null);
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  // 드래그가 끝난 직후의 click 을 막는다. 안 그러면 놓는 순간 그 타일이 다시 토글된다.
  const draggedRef = useRef(false);
  const [marquee, setMarquee] = useState<{ l: number; t: number; w: number; h: number } | null>(null);
  /** Shift+클릭 범위 선택의 기준점 */
  const anchorRef = useRef<string | null>(null);

  const selectRange = (fromId: string, toId: string) => {
    const a = items.findIndex((i) => i.id === fromId);
    const b = items.findIndex((i) => i.id === toId);
    if (a < 0 || b < 0) return;
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    setSelected((prev) => {
      const next = new Set(prev);
      for (let i = lo; i <= hi; i++) next.add(items[i].id);
      return next;
    });
  };

  const query = useInfiniteQuery({
    // 태그를 키에 넣어야 바꿀 때 목록이 새로 시작한다. 빼면 이전 태그의 페이지가
    // 남아 섞인다.
    queryKey: ["assets", tagIds],
    queryFn: ({ pageParam }) => api.assets(pageParam as string | null, tagIds),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  // 태그가 바뀐 사진만 캐시에서 갈아끼운다. 전체를 다시 불러오면 스크롤이 튀고,
  // 태그로 거르는 중이면 보던 사진이 목록에서 사라져 라이트박스가 닫힌다.
  const patchTags = (assetId: string, tags: AssetItem["tags"]) =>
    qc.setQueryData(["assets", tagIds], (old: any) =>
      old
        ? {
            ...old,
            pages: old.pages.map((page: any) => ({
              ...page,
              items: page.items.map((it: AssetItem) =>
                it.id === assetId ? { ...it, tags } : it,
              ),
            })),
          }
        : old,
    );

  const items = useMemo(
    () => query.data?.pages.flatMap((p) => p.items) ?? [],
    [query.data],
  );
  const { blocks, total } = useMemo(() => buildBlocks(items, width), [items, width]);

  /** 캔버스 기준 타일 사각형. 드래그 교차 판정에 쓴다 */
  const tileBoxes = useMemo(() => {
    const boxes: { id: string; x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const block of blocks) {
      if (block.type !== "row") continue;
      const widths = widthsOf(block.row);
      let x = 0;
      block.row.items.forEach((item, i) => {
        boxes.push({
          id: item.id,
          x1: x,
          y1: block.top,
          x2: x + widths[i],
          y2: block.top + block.height,
        });
        x += widths[i] + GAP;
      });
    }
    return boxes;
  }, [blocks]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => {
      setWidth(el.clientWidth);
      setViewportHeight(el.clientHeight);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 바닥 근처에 오면 다음 페이지를 당겨온다
  useEffect(() => {
    if (!query.hasNextPage || query.isFetchingNextPage) return;
    if (total > 0 && scrollTop + viewportHeight > total - OVERSCAN) {
      query.fetchNextPage();
    }
  }, [scrollTop, viewportHeight, total, query]);

  // 드래그 중 화면 끝에 닿으면 자동으로 스크롤한다. 없으면 한 화면 넘는 범위를
  // 고를 수 없다.
  const AUTOSCROLL_EDGE = 70;
  const AUTOSCROLL_STEP = 14;

  const applyDrag = (clientX: number, clientY: number) => {
    const drag = dragRef.current;
    const canvas = canvasRef.current;
    if (!drag || !canvas) return;

    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;

    if (Math.abs(x - drag.x) > 4 || Math.abs(y - drag.y) > 4) drag.moved = true;

    const l = Math.min(drag.x, x);
    const r = Math.max(drag.x, x);
    const tp = Math.min(drag.y, y);
    const bt = Math.max(drag.y, y);
    setMarquee({ l, t: tp, w: r - l, h: bt - tp });

    // 시작할 때의 선택에 더한다. 여러 번 나눠 끌어도 앞의 선택이 남는다.
    const next = new Set(drag.base);
    for (const box of tileBoxes) {
      if (box.x1 < r && box.x2 > l && box.y1 < bt && box.y2 > tp) next.add(box.id);
    }
    setSelected(next);
  };

  useEffect(() => {
    if (!marquee) return;
    const id = window.setInterval(() => {
      const el = scrollRef.current;
      const point = pointerRef.current;
      if (!el || !point) return;
      const box = el.getBoundingClientRect();
      const delta =
        point.y < box.top + AUTOSCROLL_EDGE
          ? -AUTOSCROLL_STEP
          : point.y > box.bottom - AUTOSCROLL_EDGE
            ? AUTOSCROLL_STEP
            : 0;
      if (delta) {
        el.scrollTop += delta;
        // 스크롤하면 캔버스가 움직이므로 같은 손 위치라도 덮는 범위가 달라진다
        applyDrag(point.x, point.y);
      }
    }, 16);
    return () => window.clearInterval(id);
  }, [marquee, tileBoxes]);

  const visible = blocks.filter(
    (b) => b.top + b.height > scrollTop - OVERSCAN && b.top < scrollTop + viewportHeight + OVERSCAN,
  );

  return (
    <div
      className="timeline"
      data-selecting={selecting}
      ref={scrollRef}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      {query.isPending && <p className="notice">불러오는 중…</p>}
      {!query.isPending && items.length === 0 && (
        <p className="notice">
          {tagIds.length
            ? tagIds.length > 1
              ? "고른 태그가 모두 붙은 사진이 없습니다."
              : "이 태그에 사진이 없습니다."
            : "아직 사진이 없습니다."}
          <br />
          드롭 폴더에 넣으면 자동으로 들어옵니다.
        </p>
      )}

      <div
        className="canvas"
        ref={canvasRef}
        style={{ height: total }}
        // 터치는 제외한다 — 끌기가 스크롤이라, 가로채면 목록을 내릴 수 없다.
        onPointerDown={(e) => {
          if (!selecting || e.pointerType === "touch" || e.button !== 0) return;
          const rect = canvasRef.current?.getBoundingClientRect();
          if (!rect) return;
          dragRef.current = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
            base: new Set(selected),
            moved: false,
          };
          pointerRef.current = { x: e.clientX, y: e.clientY };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!dragRef.current) return;
          pointerRef.current = { x: e.clientX, y: e.clientY };
          applyDrag(e.clientX, e.clientY);
        }}
        onPointerUp={() => {
          draggedRef.current = dragRef.current?.moved ?? false;
          dragRef.current = null;
          pointerRef.current = null;
          setMarquee(null);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
          pointerRef.current = null;
          setMarquee(null);
        }}
      >
        {marquee && marquee.w > 2 && marquee.h > 2 && (
          <div
            className="marquee"
            style={{ left: marquee.l, top: marquee.t, width: marquee.w, height: marquee.h }}
          />
        )}
        {visible.map((block) =>
          block.type === "header" ? (
            <h2 key={block.key} className="month" style={{ top: block.top }}>
              {block.label}
            </h2>
          ) : (
            <div key={block.key} className="row" style={{ top: block.top, height: block.height, gap: GAP }}>
              {block.row.items.map((item, i) => (
                <Tile
                  key={item.id}
                  item={item}
                  width={widthsOf(block.row)[i]}
                  height={block.height}
                  selecting={selecting}
                  selected={selected.has(item.id)}
                  // 선택 중에는 탭이 선택 토글이 된다. 라이트박스로 들어가면
                  // 여러 장 고르는 흐름이 매번 끊긴다.
                  onOpen={(mode) => {
                    // 끌어서 고른 직후의 click 은 무시한다. 안 그러면 손을 뗀
                    // 자리의 타일이 곧바로 다시 토글된다.
                    if (draggedRef.current) {
                      draggedRef.current = false;
                      return;
                    }
                    if (!selecting) {
                      setOpenIndex(items.indexOf(item));
                      return;
                    }
                    if (mode === "range" && anchorRef.current) {
                      selectRange(anchorRef.current, item.id);
                    } else {
                      anchorRef.current = item.id;
                      toggle(item.id);
                    }
                  }}
                />
              ))}
            </div>
          ),
        )}
      </div>

      {query.isFetchingNextPage && <p className="notice">더 불러오는 중…</p>}

      {selecting && (
        <SelectionBar
          ids={[...selected]}
          // 무한 스크롤이라 "모두"는 지금까지 불러온 것까지다. 개수를 함께 보여주면
          // 실제로 몇 장이 선택되는지 착각하지 않는다.
          loaded={items.length}
          onSelectAll={() => setSelected(new Set(items.map((i) => i.id)))}
          onClear={() => setSelected(new Set())}
          onSlideshow={() => onSlideshow(true)}
        >
          {tags.map((t) => (
            <RemoveFromTag
              key={t.id}
              ids={[...selected]}
              tag={t}
              onDone={() => setSelected(new Set())}
            />
          ))}
        </SelectionBar>
      )}

      {/* 고른 것이 있으면 그것만, 없으면 지금 보고 있는 목록 전체를 돌린다.
          무한 스크롤이라 "전체"는 "모두 선택"과 같은 한계 — 지금까지 불러온 만큼이다. */}
      {slideshow && (
        <Slideshow
          items={selected.size ? items.filter((i) => selected.has(i.id)) : items}
          onClose={() => onSlideshow(false)}
        />
      )}

      {openIndex !== null && (
        <Lightbox
          items={items}
          index={openIndex}
          onIndex={setOpenIndex}
          onClose={() => setOpenIndex(null)}
          onTagsChanged={patchTags}
        />
      )}
    </div>
  );
}
