import type { Metadata } from "next";
import { TraceApp } from "@/components/trace/trace-app";

export const metadata: Metadata = { title: "TRACE · In-situ" };

export default function InSituPage() {
  return <TraceApp condition="in-situ" />;
}
