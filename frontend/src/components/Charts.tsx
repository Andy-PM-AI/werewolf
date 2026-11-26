import { useMemo, useState } from "react";
import type { TimelinePoint, TypeStat, Winner } from "../lib/types";
import { pct } from "../lib/format";

const SERIES = {
  good: { label: "好人胜率", color: "#2a78d6" },
  wolf: { label: "狼人胜率", color: "#eb6834" },
  draw: { label: "未决率", color: "#8a847c" },
};

export function WinRateChart({
  points,
  upTo,
  height = 300,
}: {
  points: TimelinePoint[];
  upTo: number;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const data = useMemo(() => {
    const raw = points.slice(0, Math.max(1, upTo));
    if (raw.length <= 800) return raw;
    const step = Math.ceil(raw.length / 800);
    return raw.filter((_, index) => index % step === 0 || index === raw.length - 1);
  }, [points, upTo]);
  if (!data.length) {
    return (
      <div className="chart-empty">
        <span>完成至少一局后，这里会出现胜率曲线。</span>
      </div>
    );
  }
  const width = 860;
  const pad = { left: 46, right: 88, top: 22, bottom: 34 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const x = (index: number) => pad.left + (data.length === 1 ? innerW / 2 : (index / (data.length - 1)) * innerW);
  const y = (value: number) => pad.top + innerH - value * innerH;
  const line = (key: "wolf_rate" | "good_rate") =>
    data.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point[key]).toFixed(1)}`).join(" ");
  const area = (key: "wolf_rate" | "good_rate") => {
    if (data.length < 2) return "";
    return `${line(key)} L${x(data.length - 1).toFixed(1)},${pad.top + innerH} L${x(0).toFixed(1)},${pad.top + innerH} Z`;
  };
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const xTickCount = data.length <= 8 ? data.length : 5;
  const xTicks = Array.from({ length: xTickCount }, (_, i) => {
    const index = xTickCount === 1 ? 0 : Math.round((i / (xTickCount - 1)) * (data.length - 1));
    return { index, point: data[index] };
  });

  const hoverPoint = hover !== null ? data[Math.max(0, Math.min(data.length - 1, hover))] : null;
  const hoverX = hover !== null ? x(Math.max(0, Math.min(data.length - 1, hover))) : 0;
  const last = data[data.length - 1];
  const labelYs = useMemo(() => {
    const goodY = y(last.good_rate);
    const wolfY = y(last.wolf_rate);
    if (Math.abs(goodY - wolfY) < 22) {
      return { good: Math.min(goodY, wolfY) - 8, wolf: Math.max(goodY, wolfY) + 16 };
    }
    return { good: goodY, wolf: wolfY };
  }, [last.good_rate, last.wolf_rate]);

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    if (px < pad.left - 10 || px > pad.left + innerW + 10) {
      setHover(null);
      return;
    }
    const ratio = Math.max(0, Math.min(1, (px - pad.left) / innerW));
    setHover(Math.round(ratio * (data.length - 1)));
  };

  const tooltipWidth = 168;
  const tooltipX = Math.max(pad.left, Math.min(width - pad.right - tooltipWidth, hoverX - tooltipWidth / 2));
  const tooltipY = 8;

  return (
    <div className="win-chart">
      <div className="chart-legend">
        <span className="chart-legend__item"><i style={{ background: SERIES.good.color }} />好人胜率</span>
        <span className="chart-legend__item"><i style={{ background: SERIES.wolf.color }} />狼人胜率</span>
        <span className="chart-legend__hint">拖动下方进度条，或悬停曲线查看任一时点</span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="win-chart__svg"
        role="img"
        aria-label="狼人与好人累计胜率随局数变化"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="good-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES.good.color} stopOpacity="0.14" />
            <stop offset="100%" stopColor={SERIES.good.color} stopOpacity="0.015" />
          </linearGradient>
          <linearGradient id="wolf-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES.wolf.color} stopOpacity="0.12" />
            <stop offset="100%" stopColor={SERIES.wolf.color} stopOpacity="0.015" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={pad.left + innerW} y1={y(tick)} y2={y(tick)} className="chart-grid" />
            <text x={pad.left - 12} y={y(tick) + 4} textAnchor="end" className="chart-axis-label">
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}
        {xTicks.map(({ index, point }) => (
          <g key={`${index}-${point.no}`}>
            <line x1={x(index)} x2={x(index)} y1={pad.top} y2={pad.top + innerH} className="chart-grid chart-grid--vertical" />
            <text x={x(index)} y={height - 10} textAnchor="middle" className="chart-axis-label">
              第 {point.no} 局
            </text>
          </g>
        ))}
        {data.length > 1 ? (
          <>
            <path d={area("good_rate")} fill="url(#good-area)" />
            <path d={area("wolf_rate")} fill="url(#wolf-area)" />
          </>
        ) : null}
        <path d={line("good_rate")} className="chart-line" style={{ stroke: SERIES.good.color }} />
        <path d={line("wolf_rate")} className="chart-line" style={{ stroke: SERIES.wolf.color }} />
        <circle cx={x(data.length - 1)} cy={y(last.good_rate)} r="4" fill={SERIES.good.color} stroke="#fff" strokeWidth="2" />
        <circle cx={x(data.length - 1)} cy={y(last.wolf_rate)} r="4" fill={SERIES.wolf.color} stroke="#fff" strokeWidth="2" />
        <text x={pad.left + innerW + 12} y={labelYs.good + 4} className="chart-end-label">好人 {pct(last.good_rate)}</text>
        <text x={pad.left + innerW + 12} y={labelYs.wolf + 4} className="chart-end-label">狼人 {pct(last.wolf_rate)}</text>

        {hoverPoint ? (
          <g>
            <line x1={hoverX} x2={hoverX} y1={pad.top} y2={pad.top + innerH} className="chart-crosshair" />
            <circle cx={hoverX} cy={y(hoverPoint.good_rate)} r="4.5" fill={SERIES.good.color} stroke="#fff" strokeWidth="2" />
            <circle cx={hoverX} cy={y(hoverPoint.wolf_rate)} r="4.5" fill={SERIES.wolf.color} stroke="#fff" strokeWidth="2" />
            <g className="chart-tooltip" transform={`translate(${tooltipX},${tooltipY})`}>
              <rect width={tooltipWidth} height="66" rx="9" />
              <text x="12" y="19" className="chart-tooltip__title">第 {hoverPoint.no} 局 · 累计 {hoverPoint.games} 局</text>
              <text x="12" y="38" className="chart-tooltip__line">
                好人 {pct(hoverPoint.good_rate)}（{hoverPoint.good_wins} 胜）
              </text>
              <text x="12" y="55" className="chart-tooltip__line">
                狼人 {pct(hoverPoint.wolf_rate)}（{hoverPoint.wolf_wins} 胜）
              </text>
            </g>
          </g>
        ) : null}
      </svg>
    </div>
  );
}

export function CampSplitBar({
  camps,
  compact = false,
}: {
  camps: { wolf: number; good: number; draw: number };
  compact?: boolean;
}) {
  const total = Math.max(1, camps.wolf + camps.good + camps.draw);
  const parts: { key: Winner; value: number; label: string; color: string }[] = [
    { key: "wolf", value: camps.wolf, label: "狼人", color: SERIES.wolf.color },
    { key: "good", value: camps.good, label: "好人", color: SERIES.good.color },
    { key: "draw", value: camps.draw, label: "未决", color: SERIES.draw.color },
  ];
  return (
    <div className={`camp-split ${compact ? "camp-split--compact" : ""}`}>
      <div className="camp-split__bar">
        {parts.map((part) => (
          <span
            key={part.key}
            className="camp-split__seg"
            style={{ width: `${(part.value / total) * 100}%`, background: part.color }}
            title={`${part.label} ${part.value} 局`}
          />
        ))}
      </div>
      <div className="camp-split__legend">
        {parts.map((part) => (
          <span key={part.key}>
            <i style={{ background: part.color }} />
            {part.label} {pct(part.value / total)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function TypeRateRow({ stat, maxRate }: { stat: TypeStat; maxRate: number }) {
  const rate = stat.player_rate;
  return (
    <div className="type-rate-row">
      <div className="type-rate-row__type">
        <span className={`type-dot type-dot--${stat.type.includes("N") ? (stat.type.includes("T") ? "nt" : "nf") : (stat.type.includes("J") ? "sj" : "sp")}`} />
        <b>{stat.type}</b>
        <span>{stat.type_name}</span>
      </div>
      <div className="type-rate-row__bar">
        <span style={{ width: `${maxRate > 0 ? (rate / maxRate) * 100 : 0}%` }} />
      </div>
      <div className="type-rate-row__value">{pct(rate)}</div>
      <div className="type-rate-row__detail">
        {stat.wolf_games ? <span>狼 {pct(stat.wolf_rate)}</span> : null}
        {stat.good_games ? <span>好 {pct(stat.good_rate)}</span> : null}
        <span className="muted">{stat.games} 局</span>
      </div>
    </div>
  );
}
