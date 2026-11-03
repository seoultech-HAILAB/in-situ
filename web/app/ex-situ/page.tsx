import type { Metadata } from "next";
import { ExperimentApp } from "@/components/trace/experiment-app";

export const metadata: Metadata = { title: "TRACE · Ex-situ" };

export default function ExSituPage() {
  return <ExperimentApp condition="ex" />;
}
