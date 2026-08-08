import { describe, expect, it } from "vitest";
import { aspectOf, layoutRows, widthsOf } from "./layout";

const item = (id: string, w: number, h: number) => ({ id, width: w, height: h });

describe("justified layout", () => {
  it("한 줄이 컨테이너 폭을 정확히 채운다", () => {
    const items = Array.from({ length: 12 }, (_, i) => item(`${i}`, 4000, 3000));
    const rows = layoutRows(items, 1200, 280, 14);
    for (const row of rows.filter((r) => !r.partial)) {
      const total = widthsOf(row).reduce((a, b) => a + b, 0) + 14 * (row.items.length - 1);
      expect(total).toBeCloseTo(1200, 1);
    }
  });

  it("모든 사진이 빠짐없이 배치된다", () => {
    const items = Array.from({ length: 37 }, (_, i) => item(`${i}`, 3000, 4000));
    const placed = layoutRows(items, 1000, 280, 14).flatMap((r) => r.items);
    expect(placed.map((p) => p.id)).toEqual(items.map((i) => i.id));
  });

  it("줄 높이가 목표치를 크게 벗어나지 않는다", () => {
    const items = Array.from({ length: 30 }, (_, i) =>
      item(`${i}`, i % 2 ? 4000 : 3000, i % 2 ? 3000 : 4000),
    );
    for (const row of layoutRows(items, 1200, 280, 14).filter((r) => !r.partial)) {
      expect(row.height).toBeGreaterThan(140);
      expect(row.height).toBeLessThanOrEqual(280);
    }
  });

  it("마지막 줄은 억지로 늘리지 않는다", () => {
    // 사진 한 장만 남으면 폭에 맞춰 늘릴 때 화면을 가득 채워 어색해진다
    const rows = layoutRows([item("a", 4000, 3000)], 1200, 280, 14);
    expect(rows).toHaveLength(1);
    expect(rows[0].partial).toBe(true);
    expect(rows[0].height).toBeLessThanOrEqual(280);
  });

  it("파노라마가 줄 전체를 먹지 않는다", () => {
    expect(aspectOf(item("pano", 12000, 1000))).toBeLessThanOrEqual(3.5);
    expect(aspectOf(item("tall", 1000, 9000))).toBeGreaterThanOrEqual(0.4);
  });

  it("크기를 모르면 정사각으로 본다", () => {
    expect(aspectOf({ id: "x", width: null, height: null })).toBe(1);
    expect(aspectOf({ id: "x", width: 0, height: 0 })).toBe(1);
  });

  it("폭이 0이거나 항목이 없으면 빈 배열", () => {
    expect(layoutRows([item("a", 100, 100)], 0, 280, 14)).toEqual([]);
    expect(layoutRows([], 1200, 280, 14)).toEqual([]);
  });

  it("좁은 화면에서도 무한 루프가 없다", () => {
    const items = Array.from({ length: 20 }, (_, i) => item(`${i}`, 4000, 3000));
    const rows = layoutRows(items, 320, 280, 14);
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.flatMap((r) => r.items)).toHaveLength(20);
  });
});

describe("줄 높이 균일성", () => {
  const seeded = (n: number) => {
    // 재현 가능한 의사난수. 실제와 비슷한 비율 분포로 만든다.
    let s = 3;
    const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
    const shapes = [[4000, 3000], [3000, 4000], [2000, 2000], [5000, 2000]];
    return Array.from({ length: n }, (_, i) => {
      const [w, h] = shapes[Math.floor(rnd() * shapes.length)];
      return { id: `${i}`, width: w, height: h };
    });
  };

  it("높이가 목표에서 크게 벗어나지 않는다", () => {
    const rows = layoutRows(seeded(300), 1200, 280, 14).filter((r) => !r.partial);
    const heights = rows.map((r) => r.height);
    const avg = heights.reduce((a, b) => a + b, 0) / heights.length;

    // 탐욕적으로만 채우면 항상 한 장이 넘쳐 담겨 평균이 240px 까지 내려간다.
    expect(avg).toBeGreaterThan(260);
    expect(Math.min(...heights)).toBeGreaterThan(200);
  });

  it("가까운 쪽을 골라도 모든 사진이 배치된다", () => {
    const items = seeded(300);
    const placed = layoutRows(items, 1200, 280, 14).flatMap((r) => r.items);
    expect(placed.map((p) => p.id)).toEqual(items.map((i) => i.id));
  });

  it("완성된 줄은 여전히 폭을 정확히 채운다", () => {
    for (const row of layoutRows(seeded(200), 1000, 280, 14).filter((r) => !r.partial)) {
      const total = widthsOf(row).reduce((a, b) => a + b, 0) + 14 * (row.items.length - 1);
      expect(total).toBeCloseTo(1000, 1);
    }
  });
});
