import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, type LucideIcon } from "lucide-react";
import { cn } from "../../lib/utils";

export type NoticeTone = "info" | "success" | "warn" | "danger";

const TONE: Record<NoticeTone, { box: string; icon: LucideIcon; iconCls: string }> = {
  info: { box: "bg-accent-50", icon: Info, iconCls: "text-accent" },
  success: { box: "bg-emerald-50", icon: CheckCircle2, iconCls: "text-emerald-500" },
  warn: { box: "bg-amber-50", icon: AlertTriangle, iconCls: "text-amber-500" },
  danger: { box: "bg-red-50", icon: AlertCircle, iconCls: "text-red-500" },
};

export interface NoticeProps {
  tone: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  /** Right side, vertically centred: usually Button variant="white" size="sm". */
  action?: ReactNode;
  className?: string;
}

// A tinted inline message: an icon, a bold line, one line of body, an optional action. No border.
export function Notice({ tone, title, children, action, className }: NoticeProps) {
  const t = TONE[tone];
  const Icon = t.icon;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start gap-3 rounded-2xl px-4 py-3", t.box, className)}>
      <Icon className={cn("h-5 w-5 shrink-0", t.iconCls)} aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="text-footnote font-semibold text-zinc-900">{title}</p>}
        {children && <div className="text-footnote text-zinc-700">{children}</div>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 self-center">{action}</div>}
    </div>
  );
}
