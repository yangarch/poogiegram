/**
 * Justified layout (§7.1).
 *
 * 한 줄에 들어갈 사진들을 **같은 높이로 맞추고 가로폭을 정확히 채운다.**
 * 사진마다 비율이 다르므로 높이를 조절해 폭을 맞추는 방식이다.
 *
 * 이미지가 로드되기 전에 자리를 잡아야 스크롤 중 화면이 튀지 않는다.
 * 그래서 서버가 내려주는 width/height(EXIF 회전이 반영된 값)로 계산한다.
 */

export interface Sized {
  id: string;
  width: number | null;
  height: number | null;
}

export interface Row<T> {
  items: T[];
  height: number;
  /** 마지막 줄은 폭을 다 못 채운다 — 억지로 늘리면 사진이 커 보인다 */
  partial: boolean;
}

/** 세로·가로 어느 쪽도 극단으로 가지 않게 묶어둔다. 파노라마 한 장이 줄 전체를 먹는 것을 막는다. */
const MIN_ASPECT = 0.4;
const MAX_ASPECT = 3.5;

export function aspectOf(item: Sized): number {
  const w = item.width ?? 1;
  const h = item.height ?? 1;
  if (!w || !h) return 1;
  return Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, w / h));
}

export function layoutRows<T extends Sized>(
  items: T[],
  containerWidth: number,
  targetHeight: number,
  gap: number,
): Row<T>[] {
  if (containerWidth <= 0 || items.length === 0) return [];

  /** n장이 한 줄에 들어갈 때의 높이 */
  const heightFor = (count: number, aspects: number) =>
    (containerWidth - gap * (count - 1)) / aspects;

  const rows: Row<T>[] = [];
  let current: T[] = [];
  let aspectSum = 0;

  for (const item of items) {
    const withItem = aspectSum + aspectOf(item);
    const heightWith = heightFor(current.length + 1, withItem);

    // 이 장을 넣으면 목표보다 낮아진다. 넣은 쪽과 안 넣은 쪽 중
    // **목표에 더 가까운 쪽**을 고른다.
    //
    // 무조건 넣으면(탐욕) 항상 한 장씩 넘치게 담겨 줄이 계속 낮아진다.
    // 실측으로 목표 280px 에 평균 240px, 최저 181px 까지 벌어졌다.
    if (current.length > 0 && heightWith < targetHeight) {
      const heightWithout = heightFor(current.length, aspectSum);
      if (Math.abs(heightWithout - targetHeight) <= Math.abs(heightWith - targetHeight)) {
        rows.push({ items: current, height: heightWithout, partial: false });
        current = [item];
        aspectSum = aspectOf(item);
        continue;
      }
    }

    current.push(item);
    aspectSum = withItem;

    if (heightWith <= targetHeight) {
      rows.push({ items: current, height: heightWith, partial: false });
      current = [];
      aspectSum = 0;
    }
  }

  if (current.length > 0) {
    const available = containerWidth - gap * (current.length - 1);
    // 마지막 줄을 폭에 맞춰 늘리면 사진 한두 장이 화면을 채워 어색하다.
    // 목표 높이를 유지하되 남는 폭은 비워둔다 — 갤러리형(§7.1)에 맞는 처리다.
    rows.push({
      items: current,
      height: Math.min(targetHeight, available / aspectSum),
      partial: true,
    });
  }

  return rows;
}

/** 줄 안에서 각 사진이 차지할 폭 */
export function widthsOf<T extends Sized>(row: Row<T>): number[] {
  return row.items.map((item) => aspectOf(item) * row.height);
}
