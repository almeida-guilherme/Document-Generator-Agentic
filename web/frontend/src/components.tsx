import { Link } from "react-router-dom";
import type { RunStatus, User } from "./api";
import { STATUS_LABELS } from "./format";

/** "pidı" with the accent as the dot of the i. */
export function Logo({ to, large, label = "Pidi home" }: { to: string; large?: boolean; label?: string }) {
  return (
    <Link to={to} className={`logo${large ? " large" : ""}`} aria-label={label}>
      <span>pid</span>
      <span className="logo-i">ı</span>
    </Link>
  );
}

export function initials(user: User): string {
  const words = (user.name || user.email.split("@")[0]).split(/[\s._-]+/).filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase() || "?";
}

export function StatusPill({ status }: { status: RunStatus }) {
  return <span className={`pill pill-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function PlusIcon({ size = 16 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round">
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

export function UploadIcon({ size = 20 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13V4M6 8l4-4 4 4M4 14v2h12v-2" />
    </svg>
  );
}
