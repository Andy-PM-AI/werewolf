import type { ReactNode, SVGProps } from "react";
import type { RoleKey } from "../lib/types";

const paths: Record<string, ReactNode> = {
  users: (
    <>
      <path d="M16 21v-1.8a4 4 0 0 0-4-4H6.5a4 4 0 0 0-4 4V21" />
      <circle cx="9.2" cy="7.5" r="3.5" />
      <path d="M17 4.4a3.5 3.5 0 0 1 0 6.7M21.5 21v-1.7a4 4 0 0 0-3-3.8" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3l1.5 4.2L18 9l-4.5 1.8L12 15l-1.5-4.2L6 9l4.5-1.8L12 3Z" />
      <path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14ZM5 14l.6 1.4L7 16l-1.4.6L5 18l-.6-1.4L3 16l1.4-.6L5 14Z" />
    </>
  ),
  moon: (
    <path d="M20.2 14.2A8.2 8.2 0 0 1 9.8 3.8 8.3 8.3 0 1 0 20.2 14.2Z" />
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="3.6" />
      <path d="M12 2v2.2M12 19.8V22M2 12h2.2M19.8 12H22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M19.1 4.9l-1.6 1.6M6.5 17.5l-1.6 1.6" />
    </>
  ),
  play: <path d="M8 5.5v13l10.5-6.5L8 5.5Z" fill="currentColor" stroke="none" />,
  pause: (
    <>
      <rect x="7" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none" />
      <rect x="13.4" y="5" width="3.6" height="14" rx="1" fill="currentColor" stroke="none" />
    </>
  ),
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none" />,
  chart: (
    <>
      <path d="M4 19V5M4 19h16" />
      <path d="M7.5 15.5l3.2-4.2 3 2.4 4.8-6.2" />
      <circle cx="7.5" cy="15.5" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="10.7" cy="11.3" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="13.7" cy="13.7" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="7.5" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  history: (
    <>
      <path d="M3.5 12a8.5 8.5 0 1 0 2.2-5.7L3 9" />
      <path d="M3 4v5h5M12 7.5V12l3.2 2" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.3" />
      <path d="M15.5 15.5L21 21" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16M9 7V4.8h6V7M6.5 7l.8 13h9.4l.8-13" />
      <path d="M10 11v5.5M14 11v5.5" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
  chevronRight: <path d="M9 5l7 7-7 7" />,
  chevronLeft: <path d="M15 5l-7 7 7 7" />,
  chevronDown: <path d="M5 9l7 7 7-7" />,
  check: <path d="M4.5 12.5l5 5 10-11" />,
  alert: (
    <>
      <path d="M12 3.5L22 20.5H2L12 3.5Z" />
      <path d="M12 9.2v5.2M12 17.6v.4" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 10.6V17M12 7v.4" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14.6-4.4L3 10" />
      <path d="M3 4.5V10h5.5M4 13a8 8 0 0 0 14.6 4.4L21 14" />
      <path d="M21 19.5V14h-5.5" />
    </>
  ),
  arrowLeft: <path d="M20 12H4M10 6l-6 6 6 6" />,
  arrowUpRight: <path d="M7 17L17 7M8 7h9v9" />,
  logout: (
    <>
      <path d="M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10" />
      <path d="M15 8l4 4-4 4M19 12H9" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3.1" />
    </>
  ),
  flask: (
    <>
      <path d="M9 3h6M10 3v5.2L4.8 17a3.4 3.4 0 0 0 3 5h8.4a3.4 3.4 0 0 0 3-5L14 8.2V3" />
      <path d="M6.8 15h10.4" />
    </>
  ),
  crosshair: (
    <>
      <circle cx="12" cy="12" r="7.5" />
      <circle cx="12" cy="12" r="2.2" />
      <path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21v-1.6a5 5 0 0 1 5-5h5a5 5 0 0 1 5 5V21" />
    </>
  ),
  paw: (
    <>
      <ellipse cx="7" cy="9" rx="2" ry="2.6" />
      <ellipse cx="12" cy="6.8" rx="2" ry="2.7" />
      <ellipse cx="17" cy="9" rx="2" ry="2.6" />
      <path d="M12 11.5c3.4 0 5.8 2.2 5.8 4.6 0 2-1.6 3.4-3.6 3.1-1.4-.2-2.9-.2-4.4 0-2 .3-3.6-1.1-3.6-3.1 0-2.4 2.4-4.6 5.8-4.6Z" />
    </>
  ),
  skull: (
    <>
      <path d="M12 2.8c-4.8 0-8.2 3.4-8.2 8 0 2.8 1.3 5 3.4 6.3v2.6c0 .8.6 1.4 1.4 1.4h6.8c.8 0 1.4-.6 1.4-1.4v-2.6c2.1-1.3 3.4-3.5 3.4-6.3 0-4.6-3.4-8-8.2-8Z" />
      <circle cx="8.8" cy="11" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15.2" cy="11" r="1.5" fill="currentColor" stroke="none" />
      <path d="M10.2 16.5h3.6M9.5 20.8v-2M14.5 20.8v-2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6.5V12l3.8 2.2" />
    </>
  ),
  tokens: (
    <>
      <path d="M4 8.5l8-4.5 8 4.5-8 4.5-8-4.5Z" />
      <path d="M4 12.5l8 4.5 8-4.5M4 16.5l8 4.5 8-4.5" />
    </>
  ),
  seed: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5c2.8 2.4 4.2 5.2 4.2 8.5s-1.4 6.1-4.2 8.5c-2.8-2.4-4.2-5.2-4.2-8.5S9.2 5.9 12 3.5Z" />
      <path d="M3.5 12h17" />
    </>
  ),
  layers: (
    <>
      <path d="M12 3l9 5-9 5-9-5 9-5Z" />
      <path d="M3 12l9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  filter: <path d="M3.5 5.5h17l-6.5 7.6v5.2l-4 2v-7.2L3.5 5.5Z" />,
  grid: (
    <>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.4" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.4" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.4" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.4" />
    </>
  ),
  list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.1M3.5 12h.1M3.5 18h.1" />,
  flag: (
    <>
      <path d="M5 21V4M5 4h12l-2.2 4L17 12H5" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />,
  wave: (
    <path d="M2.5 12c2.2-5.5 4.4-5.5 6.6 0s4.4 5.5 6.6 0 4.4-5.5 6.6 0" />
  ),
  book: (
    <>
      <path d="M4 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5H4v-12.5Z" />
      <path d="M20 4.5h-4a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5H20V4.5Z" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  ...props
}: { name: string; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name] || paths.dot}
    </svg>
  );
}

export function RoleIcon({ role, size = 18 }: { role: RoleKey; size?: number }) {
  const name = role === "wolf" ? "paw" : role === "seer" ? "eye" : role === "witch" ? "flask" : role === "hunter" ? "crosshair" : "user";
  return <Icon name={name} size={size} />;
}

export function LogoMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true">
      <rect width="40" height="40" rx="11" fill="#211D19" />
      <path
        d="M27.6 25.8a9.4 9.4 0 0 1-13.4-11.6 9.4 9.4 0 1 0 13.4 11.6Z"
        fill="#C9803F"
        stroke="#C9803F"
        strokeWidth="1.2"
      />
      <circle cx="15.2" cy="14.4" r="1.15" fill="#F7F5F0" />
      <circle cx="19.7" cy="11.4" r=".8" fill="#F7F5F0" opacity=".8" />
      <path d="M28.2 11.8l.8 2.1 2.1.8-2.1.8-.8 2.1-.8-2.1-2.1-.8 2.1-.8.8-2.1Z" fill="#F7F5F0" opacity=".9" />
    </svg>
  );
}
