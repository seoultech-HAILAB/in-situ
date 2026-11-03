import type { Metadata } from "next";
import { TraceApp } from "@/components/trace/trace-app";

export const metadata: Metadata = { title: "TRACE · Ex-situ" };

export default function ExSituPage() {
  return <TraceApp condition="ex" />;
}
