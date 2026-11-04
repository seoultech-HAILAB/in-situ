import type { Metadata } from "next";
import { ExperimentApp } from "@/components/trace/experiment-app";

export const metadata: Metadata = { title: "situ" };

export default function InSituPage() {
  return <ExperimentApp condition="in-situ" />;
}
