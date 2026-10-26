/**
 * 댓글 시각 표시 (§5.6).
 *
 * 최근 것은 "3일 전"처럼 상대 시각으로 쓴다. 대화에서는 "언제쯤"이 중요하지
 * 몇 시 몇 분인지가 중요하지 않다. 일주일이 넘으면 상대 시각이 오히려 계산을
 * 시키므로 날짜로 바꾼다.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function relativeTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;

  // 시계가 조금 어긋나 미래 시각이 와도 "방금"으로 둔다
  const diff = Math.max(0, now.getTime() - d.getTime());
  if (diff < MINUTE) return "방금";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}분 전`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}시간 전`;
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)}일 전`;

  const md = `${d.getMonth() + 1}월 ${d.getDate()}일`;
  return d.getFullYear() === now.getFullYear() ? md : `${d.getFullYear()}년 ${md}`;
}
