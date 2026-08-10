/**
 * 업로드 (§6.6).
 *
 * 아이폰에서 사진을 넣을 유일한 방법이다. SFTP 는 맥에서만 되기 때문이다.
 *
 * **파일 하나당 요청 하나**로 올린다. 한 요청에 묶으면 하나가 실패했을 때 무엇이
 * 들어갔는지 알 수 없고, 진행률도 파일 단위로 못 보여준다. 동시에 두 개까지만
 * 올리는데, 모바일 회선에서 여러 개를 한꺼번에 밀면 전부 느려지고 타임아웃 위험만
 * 커진다.
 *
 * 업로드가 끝나도 화면에 바로 안 나온다 — 인제스트가 30초 안정성 검사를 거치고
 * 파생물도 만들어야 한다 (§6.1). 그래서 "올라감"과 "보임"을 구분해 알린다.
 */

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type TagItem } from "./api";

const CONCURRENCY = 2;

type Status = "waiting" | "sending" | "done" | "error";

interface Job {
  file: File;
  status: Status;
  progress: number;
  error?: string;
}

interface Props {
  tag: TagItem | null;
  onClose: () => void;
}

export function Upload({ tag, onClose }: Props) {
  const qc = useQueryClient();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tagName, setTagName] = useState(tag?.name ?? "");
  const [running, setRunning] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const update = (index: number, patch: Partial<Job>) =>
    setJobs((prev) => prev.map((j, i) => (i === index ? { ...j, ...patch } : j)));

  const start = async (files: File[]) => {
    const startAt = jobs.length;
    setJobs((prev) => [...prev, ...files.map((file) => ({ file, status: "waiting" as Status, progress: 0 }))]);
    setRunning(true);

    let next = 0;
    const worker = async () => {
      for (;;) {
        const i = next++;
        if (i >= files.length) return;
        const index = startAt + i;
        update(index, { status: "sending" });
        try {
          await api.upload(files[i], tagName.trim() || null, (p) => update(index, { progress: p }));
          update(index, { status: "done", progress: 1 });
        } catch (err) {
          update(index, { status: "error", error: err instanceof Error ? err.message : "실패" });
        }
      }
    };

    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    setRunning(false);
    // 태그 목록의 개수가 바뀐다. 타임라인은 인제스트가 끝나야 반영되므로 여기서
    // 무효화해도 아직 안 보인다 — 아래 안내 문구가 그 간극을 설명한다.
    qc.invalidateQueries({ queryKey: ["tags"] });
    qc.invalidateQueries({ queryKey: ["assets"] });
  };

  const done = jobs.filter((j) => j.status === "done").length;
  const failed = jobs.filter((j) => j.status === "error").length;

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <strong>사진 올리기</strong>
          <button className="link" onClick={onClose}>
            닫기
          </button>
        </header>

        <label className="field">
          태그
          <input
            value={tagName}
            onChange={(e) => setTagName(e.target.value)}
            placeholder="예: 푸기 3번째 생일 (비워두면 태그 없음)"
            disabled={running}
          />
        </label>

        <input
          ref={input}
          type="file"
          multiple
          // HEIC 를 명시하지 않으면 iOS 가 JPEG 로 바꿔 올리는 경우가 있다.
          accept="image/heic,image/heif,image/*,video/*"
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) start(files);
            e.target.value = "";   // 같은 파일을 다시 고를 수 있게 비운다
          }}
        />
        <button className="primary" onClick={() => input.current?.click()} disabled={running}>
          {running ? "올리는 중…" : "사진 고르기"}
        </button>

        {jobs.length > 0 && (
          <>
            <ul className="up-list">
              {jobs.map((job, i) => (
                <li key={i} data-status={job.status}>
                  <span className="up-name">{job.file.name}</span>
                  {job.status === "sending" && (
                    <span className="up-bar">
                      <span style={{ width: `${Math.round(job.progress * 100)}%` }} />
                    </span>
                  )}
                  {job.status === "done" && <span className="up-ok">✓</span>}
                  {job.status === "error" && <span className="up-err">{job.error}</span>}
                </li>
              ))}
            </ul>

            {!running && done > 0 && (
              // 올라간 것과 보이는 것은 다르다. 이 설명이 없으면 "안 올라갔나?" 가 된다.
              <p className="up-note">
                {done}장 올렸습니다{failed > 0 && `, ${failed}장 실패`}. 처리에 1~2분
                걸리니 잠시 뒤 새로고침하면 보입니다.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
