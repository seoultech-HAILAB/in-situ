"use client";

import { useState } from "react";
import Image from "next/image";
import { logStudy } from "@/lib/study-telemetry";
import manifest from "./task-guides/manifest.json";
import tutorial from "./task-guides/tutorial.png";
import t01 from "./task-guides/t01.png";
import t03 from "./task-guides/t03.png";
import t07 from "./task-guides/t07.png";

const images = { "PILOT4-TRAIN": tutorial, "PILOT4-T01": t01, "PILOT4-T03": t03, "PILOT4-T07": t07 };
export const TASK_GUIDE_VERSION = manifest.source_sha256;

/** Faithful pages of the participant handout, independent of task Python/prose. */
export function ParticipantTaskGuide({ taskId, onReady }: { taskId: string; onReady?: (ready: boolean) => void }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const id = taskId as keyof typeof images;
  const image = images[id], page = manifest.pages[id];
  if (!image || !page) return <p role="alert">이 과제의 안내 자료를 찾을 수 없습니다.</p>;
  return <div className="participant-task-guide" data-guide-task={taskId} data-guide-page={page.page}>
    <Image key={attempt} src={image} alt={`${taskId === "PILOT4-TRAIN" ? "튜토리얼" : taskId.replace("PILOT4-", "")} 과제 안내: 입력 자료, 처리 조건, 목표 결과`} unoptimized loading="eager"
      onLoad={() => { setFailed(false); onReady?.(true); logStudy("instructions.loaded", { task_id: taskId, page: page.page, guide_version: TASK_GUIDE_VERSION }); }}
      onError={() => { setFailed(true); onReady?.(false); logStudy("instructions.failed", { task_id: taskId, page: page.page }); }} />
    <div className="sr-only">{page.text}</div>
    {failed && <div className="study-guide-error" role="alert">과제 안내를 불러오지 못했습니다. <button className="study-button secondary" onClick={() => { setFailed(false); setAttempt(value => value + 1); }}>다시 불러오기</button></div>}
  </div>;
}
