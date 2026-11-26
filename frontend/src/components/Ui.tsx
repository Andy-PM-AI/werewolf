import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icons";
import { GROUP_LABEL, TYPE_NAMES, groupOf } from "../lib/format";
import type { RoleKey, SimStatus, Winner } from "../lib/types";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "dark" | "ochre";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading,
  className = "",
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: string;
  loading?: boolean;
}) {
  return (
    <button
      className={`btn btn--${variant} btn--${size} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <span className="spinner spinner--sm" /> : icon ? <Icon name={icon} size={size === "sm" ? 15 : 17} /> : null}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string }) {
  return (
    <button className={`icon-btn ${className}`} aria-label={label} title={label} {...props}>
      <Icon name={icon} size={18} />
    </button>
  );
}

export function Spinner({ size = 20 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} />;
}

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return <section className={`card ${padded ? "card--padded" : ""} ${className}`}>{children}</section>;
}

export function SectionHead({
  eyebrow,
  title,
  desc,
  actions,
}: {
  eyebrow?: string;
  title: ReactNode;
  desc?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="section-head">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h2 className="section-title">{title}</h2>
        {desc ? <p className="section-desc">{desc}</p> : null}
      </div>
      {actions ? <div className="section-actions">{actions}</div> : null}
    </div>
  );
}

export function TypeBadge({
  type,
  name,
  showName = false,
  size = "md",
}: {
  type: string;
  name?: string;
  showName?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const group = groupOf(type);
  const label = name || TYPE_NAMES[type] || GROUP_LABEL[group];
  return (
    <span className={`type-badge type-${group.toLowerCase()} type-badge--${size}`} title={`${type} · ${label}`}>
      <span className="type-badge__code">{type}</span>
      {showName ? <span className="type-badge__name">{label}</span> : null}
    </span>
  );
}

export function RoleBadge({ role, name, size = "md" }: { role: RoleKey; name?: string; size?: "sm" | "md" }) {
  const label = name || { wolf: "狼人", villager: "平民", seer: "预言家", witch: "女巫", hunter: "猎人" }[role];
  return (
    <span className={`role-badge role-badge--${role} role-badge--${size}`}>
      <Icon name={role === "wolf" ? "paw" : role === "seer" ? "eye" : role === "witch" ? "flask" : role === "hunter" ? "crosshair" : "user"} size={12} />
      {label}
    </span>
  );
}

export function WinnerBadge({ winner, size = "md" }: { winner: Winner; size?: "sm" | "md" }) {
  const label = winner === "wolf" ? "狼人胜" : winner === "good" ? "好人胜" : "未决";
  return (
    <span className={`winner-badge winner-badge--${winner} winner-badge--${size}`}>
      <span className="winner-badge__dot" />
      {label}
    </span>
  );
}

const STATUS_LABEL: Record<SimStatus, string> = {
  created: "待启动",
  running: "运行中",
  paused: "已暂停",
  stopping: "正在停止",
  stopped: "已停止",
  completed: "已完成",
  error: "出错",
};

export function StatusBadge({ status }: { status: SimStatus }) {
  return (
    <span className={`status-badge status-badge--${status}`}>
      <span className="status-badge__dot" />
      {STATUS_LABEL[status] || status}
    </span>
  );
}

export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: string;
  tone?: "default" | "ochre" | "good" | "wolf" | "violet";
}) {
  return (
    <div className={`stat-tile stat-tile--${tone}`}>
      <div className="stat-tile__top">
        <span className="stat-tile__label">{label}</span>
        {icon ? <span className="stat-tile__icon"><Icon name={icon} size={16} /></span> : null}
      </div>
      <div className="stat-tile__value">{value}</div>
      {hint ? <div className="stat-tile__hint">{hint}</div> : null}
    </div>
  );
}

export function ProgressBar({
  value,
  max = 100,
  tone = "ochre",
  height = 8,
  shimmer = false,
}: {
  value: number;
  max?: number;
  tone?: "ochre" | "good" | "wolf" | "ink" | "violet";
  height?: number;
  shimmer?: boolean;
}) {
  const width = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={`progress progress--${tone}`} style={{ height }} role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className={`progress__fill ${shimmer ? "progress__fill--shimmer" : ""}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = "md",
  className = "",
  closable = true,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
  closable?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && closable) onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose, closable]);

  if (!open) return null;
  return createPortal(
    <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && closable && onClose()}>
      <div className={`modal modal--${size} ${className}`} role="dialog" aria-modal="true">
        {title ? (
          <div className="modal__head">
            <div>
              <h3 className="modal__title">{title}</h3>
              {subtitle ? <p className="modal__subtitle">{subtitle}</p> : null}
            </div>
            {closable ? (
              <IconButton icon="close" label="关闭" onClick={onClose} />
            ) : null}
          </div>
        ) : null}
        <div className="modal__body">{children}</div>
        {footer ? <div className="modal__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({
  open,
  onClose,
  children,
  width = 780,
  dark = false,
  label = "详情",
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  width?: number;
  dark?: boolean;
  label?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="overlay overlay--drawer" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside
        className={`drawer ${dark ? "drawer--dark" : ""}`}
        style={{ width: `min(${width}px, 94vw)` }}
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        {children}
      </aside>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = "确认",
  cancelText = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: ReactNode;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>{cancelText}</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmText}</Button>
        </>
      }
    >
      <div className="confirm-message">{message}</div>
    </Modal>
  );
}

export function EmptyState({
  icon = "moon",
  title,
  desc,
  action,
}: {
  icon?: string;
  title: string;
  desc?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon"><Icon name={icon} size={28} /></div>
      <h3>{title}</h3>
      {desc ? <p>{desc}</p> : null}
      {action ? <div className="empty-state__action">{action}</div> : null}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`field ${className}`}>
      <span className="field__label">{label}</span>
      {children}
      {hint ? <span className="field__hint">{hint}</span> : null}
    </label>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div className={`segmented segmented--${size}`}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`segmented__item ${value === option.value ? "is-active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; icon?: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          aria-selected={value === option.value}
          className={`tabs__item ${value === option.value ? "is-active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.icon ? <Icon name={option.icon} size={15} /> : null}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Meter({
  value,
  label,
  tone = "ochre",
}: {
  value: number;
  label?: ReactNode;
  tone?: "ochre" | "good" | "wolf" | "ink" | "violet";
}) {
  return (
    <div className="meter">
      <div className="meter__track">
        <div className={`meter__fill meter__fill--${tone}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
      {label ? <span className="meter__label">{label}</span> : null}
    </div>
  );
}

// ------------------------------------------------------------------ toasts
type ToastTone = "default" | "success" | "error" | "info";
interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}
const ToastContext = createContext<{ push: (message: string, tone?: ToastTone) => void }>({
  push: () => undefined,
});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((message: string, tone: ToastTone = "default") => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }, []);
  const value = useMemo(() => ({ push }), [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack">
        {items.map((item) => (
          <div key={item.id} className={`toast toast--${item.tone}`}>
            <Icon name={item.tone === "success" ? "check" : item.tone === "error" ? "alert" : "info"} size={16} />
            <span>{item.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
