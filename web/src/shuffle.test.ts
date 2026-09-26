import { describe, expect, it } from "vitest";
import { advance, back, cycle, shuffle, start, type Queue } from "./shuffle";

/** 결정적인 난수. 같은 씨앗이면 같은 순서가 나와야 실패를 재현할 수 있다 (mulberry32) */
function prng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ids = (n: number) => Array.from({ length: n }, (_, i) => `a${i}`);

/** 큐를 n 번 넘기며 지나간 사진을 순서대로 모은다 */
function walk(q: Queue, pool: string[], steps: number, random: () => number): string[] {
  const seen = [q.order[q.cursor]];
  for (let i = 0; i < steps; i++) {
    q = advance(q, pool, random);
    seen.push(q.order[q.cursor]);
  }
  return seen;
}

describe("shuffle", () => {
  it("빠뜨리거나 늘리지 않는다", () => {
    const pool = ids(50);
    expect(shuffle(pool, prng(1)).sort()).toEqual(pool.slice().sort());
  });

  it("원본 배열을 건드리지 않는다", () => {
    const pool = ids(10);
    shuffle(pool, prng(2));
    expect(pool).toEqual(ids(10));
  });
});

describe("바퀴 이어붙이기", () => {
  it("앞바퀴 마지막 장으로 새 바퀴를 시작하지 않는다", () => {
    const pool = ids(4);
    // 4장이면 우연히 걸릴 확률이 1/4 이라 여러 씨앗으로 확인해야 의미가 있다
    for (let seed = 0; seed < 200; seed++) {
      expect(cycle(pool, "a2", prng(seed))[0]).not.toBe("a2");
    }
  });

  it("한 장뿐이면 어쩔 수 없이 같은 사진이 이어진다", () => {
    expect(cycle(["only"], "only", prng(3))).toEqual(["only"]);
  });
});

describe("슬라이드 쇼 순서", () => {
  it("한 바퀴 안에서는 같은 사진이 두 번 나오지 않는다", () => {
    const pool = ids(12);
    const random = prng(7);
    const seen = walk(start(pool, random), pool, pool.length - 1, random);
    expect(new Set(seen).size).toBe(pool.length);
    expect(seen.slice().sort()).toEqual(pool.slice().sort());
  });

  it("여러 바퀴를 돌아도 같은 사진이 연달아 나오지 않는다", () => {
    const pool = ids(5);
    const random = prng(11);
    const seen = walk(start(pool, random), pool, 200, random);
    for (let i = 1; i < seen.length; i++) {
      expect(seen[i]).not.toBe(seen[i - 1]);
    }
  });

  it("다음 장이 항상 정해져 있다 — 미리 받아둘 수 있어야 한다", () => {
    const pool = ids(6);
    const random = prng(13);
    let q = start(pool, random);
    for (let i = 0; i < 60; i++) {
      expect(q.order[q.cursor + 1]).toBeDefined();
      q = advance(q, pool, random);
    }
  });

  it("되돌아가면 방금 본 사진이 나오고, 다시 넘기면 같은 순서로 이어진다", () => {
    const pool = ids(8);
    const random = prng(17);
    let q = start(pool, random);
    q = advance(q, pool, random);
    const here = q.order[q.cursor];
    const before = q.order[q.cursor - 1];

    q = back(q);
    expect(q.order[q.cursor]).toBe(before);
    q = advance(q, pool, random);
    expect(q.order[q.cursor]).toBe(here); // 되돌아갔다 와서 순서가 다시 섞이면 안 된다
  });

  it("맨 앞에서 되돌아가려 해도 넘어가지 않는다", () => {
    const pool = ids(4);
    const q = start(pool, prng(19));
    expect(back(q)).toEqual(q);
  });

  it("오래 켜둬도 이력이 무한히 쌓이지 않는다", () => {
    const pool = ids(10);
    const random = prng(23);
    let q = start(pool, random);
    for (let i = 0; i < 5000; i++) q = advance(q, pool, random);
    expect(q.order.length).toBeLessThan(1000);
    // 잘라낸 뒤에도 지금 보는 사진과 다음 장은 남아 있어야 한다
    expect(q.order[q.cursor]).toBeDefined();
    expect(q.order[q.cursor + 1]).toBeDefined();
  });

  it("사진이 없으면 빈 큐가 되고 넘겨도 터지지 않는다", () => {
    const q = start([], prng(29));
    expect(q.order).toEqual([]);
    expect(advance(q, [], prng(29))).toEqual(q);
    expect(back(q)).toEqual(q);
  });

  it("한 장만 골랐으면 그 한 장을 계속 보여준다", () => {
    const random = prng(31);
    let q = start(["one"], random);
    for (let i = 0; i < 10; i++) {
      expect(q.order[q.cursor]).toBe("one");
      q = advance(q, ["one"], random);
    }
  });
});
