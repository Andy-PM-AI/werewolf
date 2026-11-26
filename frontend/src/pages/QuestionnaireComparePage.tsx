import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type { QuestionnaireComparison } from "../lib/types";
import { Button, EmptyState, Modal, SectionHead, Spinner, StatTile, useToast } from "../components/Ui";
import { Icon } from "../components/Icons";

function Rate({ value }: { value: number }) {
  return <>{Math.round(value * 1000) / 10}%</>;
}

function ResultChip({ value }: { value: string }) {
  return <span className={`result-chip ${value ? "" : "result-chip--empty"}`}>{value || "—"}</span>;
}

export function QuestionnaireComparePage({
  left,
  right,
  onNavigate,
}: {
  left: string;
  right: string;
  onNavigate: (path: string) => void;
}) {
  const toast = useToast();
  const [data, setData] = useState<QuestionnaireComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [bucket, setBucket] = useState<QuestionnaireComparison["distribution"][number] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.compareQuestionnaires(left, right)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) toast.push(err instanceof Error ? err.message : "读取对比结果失败", "error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [left, right, toast]);

  const diffRate = useMemo(() => data?.different_rate || 0, [data]);

  return (
    <div className="page questionnaire-compare-page">
      <div className="page-head">
        <div>
          <button type="button" className="back-link" onClick={() => onNavigate("/questionnaires")}>
            <Icon name="arrowLeft" size={15} /> 问卷管理
          </button>
          <div className="eyebrow">QUESTIONNAIRE COMPARE · 双问卷一致性</div>
          <h1 className="page-title">问卷对比</h1>
          {data ? (
            <p className="page-desc">
              <b>{data.left.name}</b> vs <b>{data.right.name}</b> · 只统计同时拥有两套问卷结果的玩家。
            </p>
          ) : null}
        </div>
        <div className="page-actions">
          <Button variant="secondary" icon="layers" onClick={() => onNavigate("/questionnaires")}>返回问卷管理</Button>
        </div>
      </div>

      {loading ? (
        <div className="panel-loading page-loading"><Spinner size={28} /><span>正在汇总两份问卷结果…</span></div>
      ) : !data ? (
        <EmptyState icon="alert" title="没有对比结果" desc="请确认两份问卷都存在，且至少有一位玩家同时完成两份问卷。" />
      ) : data.total === 0 ? (
        <EmptyState icon="chart" title="没有可对比的玩家" desc="当前没有玩家同时拥有这两套问卷的结果。先分别对玩家完成两套问卷测试。" />
      ) : (
        <>
          <div className="stat-row">
            <StatTile label="有效样本" value={data.total} hint="同时拥有两份结果" icon="users" tone="ochre" />
            <StatTile label="结论一致" value={`${data.same} 人`} hint={`占比 ${Math.round(data.same_rate * 1000) / 10}%`} icon="check" tone="good" />
            <StatTile label="结论不一致" value={`${data.different} 人`} hint={`占比 ${Math.round(data.different_rate * 1000) / 10}%`} icon="alert" tone="wolf" />
            <StatTile label="不一致率" value={<Rate value={diffRate} />} hint="不一致人数 / 有效样本" icon="chart" tone="violet" />
          </div>

          <section className="compare-card">
            <SectionHead
              eyebrow="AGREEMENT"
              title="总体一致性"
              desc="“一致”指两套问卷得到完全相同的人格结果代码；“不一致”按左侧结果 → 右侧结果聚类。"
            />
            <div className="compare-bars">
              <div className="compare-bars__row">
                <span>一致</span>
                <div className="compare-bars__track"><span id="same" style={{ width: `${data.same_rate * 100}%` }} /></div>
                <b>{data.same} 人 · {Math.round(data.same_rate * 1000) / 10}%</b>
              </div>
              <div className="compare-bars__row">
                <span>不一致</span>
                <div className="compare-bars__track"><span id="diff" style={{ width: `${data.different_rate * 100}%` }} /></div>
                <b>{data.different} 人 · {Math.round(data.different_rate * 1000) / 10}%</b>
              </div>
            </div>
          </section>

          <section className="compare-card">
            <SectionHead
              eyebrow="DISTRIBUTION"
              title="不一致分布"
              desc="每一行是一组 [问卷 1 结果 vs 问卷 2 结果]；点击查看具体玩家。"
              actions={<span className="section-progress">{data.distribution.length} 组</span>}
            />
            {data.distribution.length === 0 ? (
              <EmptyState icon="check" title="全部一致" desc="同时完成两套问卷的玩家得到了相同结果。" />
            ) : (
              <div className="compare-table-wrap">
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>问卷 1 结果</th>
                      <th>问卷 2 结果</th>
                      <th>人数</th>
                      <th>占不一致人数</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.distribution.map((row) => (
                      <tr key={`${row.left_result}-${row.right_result}`}>
                        <td><ResultChip value={row.left_result} /></td>
                        <td><ResultChip value={row.right_result} /></td>
                        <td><b>{row.count}</b> 人</td>
                        <td>{data.different ? Math.round((row.count / data.different) * 1000) / 10 : 0}%</td>
                        <td><button type="button" className="link-btn" onClick={() => setBucket(row)}>查看玩家</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {data.same_players.length ? (
            <section className="compare-card compare-card--muted">
              <SectionHead eyebrow="SAME" title="结果一致的玩家" desc="两套问卷得到相同结果代码的玩家。" />
              <div className="compare-same-list">
                {data.same_players.slice(0, 30).map((player) => (
                  <span className="compare-player-chip" key={player.id}>
                    {player.name} <ResultChip value={player.left_result} />
                  </span>
                ))}
                {data.same_players.length > 30 ? <span className="muted">等 {data.same_players.length} 人</span> : null}
              </div>
            </section>
          ) : null}
        </>
      )}

      <Modal
        open={Boolean(bucket)}
        onClose={() => setBucket(null)}
        title="不一致玩家"
        subtitle={bucket ? `问卷 1：${bucket.left_result} · 问卷 2：${bucket.right_result} · ${bucket.count} 人` : undefined}
        size="md"
        footer={<Button variant="ghost" onClick={() => setBucket(null)}>关闭</Button>}
      >
        <div className="compare-player-list">
          {bucket?.players.map((player) => (
            <div className="compare-player" key={player.id}>
              <div className="compare-player__avatar">{player.name.slice(0, 1)}</div>
              <div>
                <b>{player.name}</b>
                <span>{player.age ? `${player.age}岁` : "年龄未知"} · {player.gender || "性别未知"} · {player.province || "地区未知"} · {player.occupation || "职业未知"}</span>
              </div>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
