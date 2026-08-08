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
import { useInfiniteQuery } from "@tanstack/react-query";
import { api, assetUrl, type AssetItem } from "./api";
import { layoutRows, widthsOf, type Row } from "./layout";
import { Lightbox } from "./Lightbox";

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
}: {
  item: AssetItem;
  width: number;
  height: number;
  onOpen: () => void;
}) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div
      className="tile"
      style={{ width, height }}
      data-ready={item.ready}
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
    </div>
  );
}

export function Timeline() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  const query = useInfiniteQuery({
    queryKey: ["assets"],
    queryFn: ({ pageParam }) => api.assets(pageParam as string | null),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });

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
          아직 사진이 없습니다.
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
                  onOpen={() => setOpenIndex(items.indexOf(item))}
                />
              ))}
            </div>
          ),
        )}
      </div>

      {query.isFetchingNextPage && <p className="notice">더 불러오는 중…</p>}

      {openIndex !== null && (
        <Lightbox
          items={items}
          index={openIndex}
          onIndex={setOpenIndex}
          onClose={() => setOpenIndex(null)}
        />
      )}
    </div>
  );
}
