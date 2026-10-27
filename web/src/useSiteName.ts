/**
 * 화면 이름 (§3.5).
 *
 * 같은 이미지로 인스턴스를 여럿 띄우므로 이름을 빌드에 굽지 않고 서버에서 받는다.
 * 탭 제목도 여기서 바꾼다 — 푸기와 모코를 같이 열어 두면 탭으로만 구분된다.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** 받아오기 전·실패했을 때 쓰는 이름. index.html 의 <title> 과 같다 */
const FALLBACK = "poogiegram";

export function useSiteName(): string {
  const site = useQuery({ queryKey: ["site"], queryFn: api.site, staleTime: Infinity });
  const name = site.data?.name ?? FALLBACK;

  useEffect(() => {
    document.title = name;
  }, [name]);

  return name;
}
