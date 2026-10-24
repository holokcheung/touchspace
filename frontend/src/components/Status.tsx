import type { ReactNode } from "react";

type Tone = "info" | "success" | "warning" | "error";

const TONES: Record<Tone, { cls: string; label: string }> = {
  info: { cls: "border-line bg-surface-2", label: "Note" },
  success: { cls: "border-ok bg-ok-soft", label: "Done" },
  warning: { cls: "border-warn bg-warn-soft", label: "Warning" },
  error: { cls: "border-danger bg-danger-soft", label: "Error" },
};

/** A message box whose tone is also spelled out in text, so it never relies on color alone. */
export function Notice({ tone, title, children }: { tone: Tone; title?: string; children?: ReactNode }) {
  const t = TONES[tone];
  return (
    <div className={`rounded-lg border-l-4 border p-4 ${t.cls}`} role={tone === "error" ? "alert" : undefined}>
      <p className="font-bold">
        {t.label}
        {title ? `: ${title}` : ""}
      </p>
      {children && <div className="mt-1">{children}</div>}
    </div>
  );
}

/** Polite live region for progress updates ("Saving…", "Saved"). */
export function LiveStatus({ message }: { message: string }) {
  return (
    <p role="status" aria-live="polite" className="min-h-6 text-sm text-muted">
      {message}
    </p>
  );
}
