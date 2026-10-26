import { describe, expect, it } from "vitest";
import { relativeTime } from "./when";

const NOW = new Date(2026, 9, 26, 15, 0, 0);
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();

describe("relativeTime", () => {
  it("일주일 안은 상대 시각", () => {
    expect(relativeTime(ago(10_000), NOW)).toBe("방금");
    expect(relativeTime(ago(5 * 60_000), NOW)).toBe("5분 전");
    expect(relativeTime(ago(3 * 3_600_000), NOW)).toBe("3시간 전");
    expect(relativeTime(ago(3 * 86_400_000), NOW)).toBe("3일 전");
  });

  it("일주일이 넘으면 날짜 — 올해면 연도를 생략한다", () => {
    expect(relativeTime(new Date(2026, 7, 8, 9).toISOString(), NOW)).toBe("8월 8일");
    expect(relativeTime(new Date(2025, 7, 8, 9).toISOString(), NOW)).toBe("2025년 8월 8일");
  });

  it("시계가 어긋나 미래 시각이 와도 음수를 보이지 않는다", () => {
    expect(relativeTime(ago(-30_000), NOW)).toBe("방금");
  });
});
