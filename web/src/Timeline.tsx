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
  onOpen: () => void;
  selecting: boolean;
  selected: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div
      className="tile"
      style={{ width, height }}
      data-ready={item.ready}
      data-selected={selected}
      onClick={onOpen}
      // 키보드로도 열려야 한다 — 그리드 전체가 마우스 전용이 되면 곤란하다
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
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
  tag,
  selectMode,
  onExitSelect,
}: {
  tag: TagItem | null;
  selectMode: boolean;
  onExitSelect: () => void;
}) {
  const tagId = tag?.id ?? null;
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

  const query = useInfiniteQuery({
    // 태그를 키에 넣어야 바꿀 때 목록이 새로 시작한다. 빼면 이전 태그의 페이지가
    // 남아 섞인다.
    queryKey: ["assets", tagId],
    queryFn: ({ pageParam }) => api.assets(pageParam as string | null, tagId),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

  // 태그가 바뀐 사진만 캐시에서 갈아끼운다. 전체를 다시 불러오면 스크롤이 튀고,
  // 태그로 거르는 중이면 보던 사진이 목록에서 사라져 라이트박스가 닫힌다.
  const patchTags = (assetId: string, tags: AssetItem["tags"]) =>
    qc.setQueryData(["assets", tagId], (old: any) =>
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

  const visible = blocks.filter(
    (b) => b.top + b.height > scrollTop - OVERSCAN && b.top < scrollTop + viewportHeight + OVERSCAN,
  );

  return (
    <div
      className="timeline"
      ref={scrollRef}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      {query.isPending && <p className="notice">불러오는 중…</p>}
      {!query.isPending && items.length === 0 && (
        <p className="notice">
          {tagId ? "이 태그에 사진이 없습니다." : "아직 사진이 없습니다."}
          <br />
          드롭 폴더에 넣으면 자동으로 들어옵니다.
        </p>
      )}

      <div className="canvas" style={{ height: total }}>
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
                  onOpen={() =>
                    selecting ? toggle(item.id) : setOpenIndex(items.indexOf(item))
                  }
                />
              ))}
            </div>
          ),
        )}
      </div>

      {query.isFetchingNextPage && <p className="notice">더 불러오는 중…</p>}

      {selecting && selected.size > 0 && (
        <SelectionBar ids={[...selected]} onClear={onExitSelect}>
          {tag && (
            <RemoveFromTag ids={[...selected]} tag={tag} onDone={onExitSelect} />
          )}
        </SelectionBar>
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
