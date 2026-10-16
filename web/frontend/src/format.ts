import type { RunStatus } from "./api";

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Processing",
  done: "Ready",
  failed: "Failed",
};

// The pipeline's stages (pipeline.STAGES and TEMPLATE_STAGES), as the user sees them.
export const STAGE_LABELS: Record<string, string> = {
  analyze_template: "Read the company template",
  extract_frames: "Find screen changes",
  caption: "Describe each screenshot",
  transcribe: "Transcribe the narration",
  structure: "Work out the process steps",
  verify_names: "Double-check file and screen names",
  fill_template: "Write the template's sections",
  render: "Write the document",
};

// What the template analysis decided for a part of the template.
export const TEMPLATE_ACTIONS: Record<string, { label: string; tone: "keep" | "remove" | "fill" }> = {
  keep: { label: "Kept", tone: "keep" },
  remove: { label: "Removed", tone: "remove" },
  write: { label: "Written for each process", tone: "fill" },
  table_rows: { label: "Rows filled", tone: "fill" },
  table_answers: { label: "Answers filled", tone: "fill" },
  diagram: { label: "Process diagram", tone: "fill" },
  steps: { label: "Steps with screenshots", tone: "fill" },
};

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

export function dateTime(iso: string): string {
  // The API sends UTC; SQLite drops the zone, so mark it as UTC before converting to local time.
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function bytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export const INPUT_KINDS = { structured: "Structured", semi_structured: "Semi-structured", unstructured: "Unstructured" };

export const REQUIREMENT_LABELS: Record<string, string> = {
  frequency: "Frequency",
  volume: "Volume",
  business_rule: "Business rule",
  reference_data: "Reference data",
  access: "Access",
  other: "Other",
};
