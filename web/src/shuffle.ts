/**
 * 슬라이드 쇼의 순서 만들기 (§7.2).
 *
 * `Math.random()` 으로 매번 한 장씩 뽑으면 **방금 본 사진이 곧바로 또 나온다.**
 * 대신 순열을 만들어 소진한다 — 한 바퀴 안에서는 같은 사진이 두 번 나오지 않고,
 * 덤으로 **다음 장이 미리 정해져 프리로드가 된다.** 액자 모드는 전환이 즉각적이어야
 * 하는데 1분 간격이면 미리 받아둘 시간은 남아돈다.
 *
 * 지나간 순서를 버리지 않는 이유는 되돌아가기(←) 하나뿐이다. 무작위라 다시
 * 계산해서 복원할 방법이 없다.
 */

/** 현재 위치 뒤로 남겨두는 이력의 한계. 며칠씩 켜두면 계속 쌓이므로 자른다 */
const HISTORY_CAP = 600;

export interface Queue {
  /** 지나간 것 + 앞으로 볼 것을 한 줄로 이어둔다. `cursor` 가 지금 보는 위치다 */
  order: string[];
  cursor: number;
}

/** Fisher-Yates. `random` 을 받는 건 테스트에서 순서를 고정하기 위해서다 */
export function shuffle<T>(items: readonly T[], random: () => number = Math.random): T[] {
  const out = items.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * 새 바퀴를 만든다.
 *
 * 앞바퀴의 마지막 장이 새 바퀴의 첫 장으로 뽑히면 경계에서 같은 사진이 연달아 두 번
 * 나온다. 확률적으로는 정상이지만 보는 쪽에서는 고장으로 읽히므로 뒤로 민다.
 */
export function cycle(
  ids: readonly string[],
  after: string | null,
  random: () => number = Math.random,
): string[] {
  const next = shuffle(ids, random);
  if (next.length > 1 && after !== null && next[0] === after) {
    const at = 1 + Math.floor(random() * (next.length - 1));
    [next[0], next[at]] = [next[at], next[0]];
  }
  return next;
}

/** 다음 장이 항상 정해져 있어야 미리 받아둘 수 있다 */
function ensureNext(
  order: string[],
  cursor: number,
  ids: readonly string[],
  random: () => number,
): string[] {
  if (ids.length === 0 || cursor + 1 < order.length) return order;
  return order.concat(cycle(ids, order[order.length - 1] ?? null, random));
}

export function start(ids: readonly string[], random: () => number = Math.random): Queue {
  const order = ids.length ? cycle(ids, null, random) : [];
  return { order: ensureNext(order, 0, ids, random), cursor: 0 };
}

export function advance(
  q: Queue,
  ids: readonly string[],
  random: () => number = Math.random,
): Queue {
  if (!q.order.length) return q;

  let cursor = Math.min(q.cursor + 1, q.order.length - 1);
  let order = ensureNext(q.order, cursor, ids, random);

  // 오래된 이력을 버린다. 앞을 자르면 인덱스가 밀리므로 cursor 도 같이 당겨야
  // 지금 보는 사진이 유지된다.
  if (cursor > HISTORY_CAP) {
    order = order.slice(cursor - HISTORY_CAP);
    cursor = HISTORY_CAP;
  }
  return { order, cursor };
}

/** 맨 앞에서 더 되돌아가지는 않는다 — 이력이 없는 방향이다 */
export function back(q: Queue): Queue {
  return q.cursor > 0 ? { order: q.order, cursor: q.cursor - 1 } : q;
}
