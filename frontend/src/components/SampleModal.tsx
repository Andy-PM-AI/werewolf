import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Catalog, SampleJob } from "../lib/types";
import { TYPE_NAMES, groupOf } from "../lib/format";
import { Button, Field, Modal, ProgressBar, Segmented, TypeBadge, useToast } from "./Ui";
import { Icon } from "./Icons";

const FALLBACK_COUNTRIES = [{ code: "CN", name: "中国" }];

export function SampleModal({
  open,
  onClose,
  catalog,
  onDone,
  questionnaireName,
}: {
  open: boolean;
  onClose: () => void;
  catalog: Catalog | null;
  onDone: () => void;
  questionnaireName?: string;
}) {
  const toast = useToast();
  const countries = useMemo(() => {
    const list = catalog ? Object.values(catalog.countries) : [];
    return list.length ? list.map((c) => ({ code: c.code, name: c.name })) : FALLBACK_COUNTRIES;
  }, [catalog]);
  const [country, setCountry] = useState(countries[0]?.code || "CN");
  const [ageMin, setAgeMin] = useState<string>("");
  const [ageMax, setAgeMax] = useState<string>("");
  const [gender, setGender] = useState("");
  const [education, setEducation] = useState("");
  const [occupation, setOccupation] = useState("");
  const [urbanicity, setUrbanicity] = useState("");
  const [style, setStyle] = useState("");
  const [count, setCount] = useState(10);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<SampleJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const notified = useRef(false);
  const onDoneRef = useRef(onDone);
  const toastRef = useRef(toast);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);
  useEffect(() => {
    toastRef.current = toast;
  }, [toast]);

  const selectedCountry = catalog?.countries?.[country];
  const facets = selectedCountry?.items?.[0]?.facets || {};
  const running = job ? job.status === "queued" || job.status === "running" : false;

  useEffect(() => {
    if (countries.length && !countries.some((item) => item.code === country)) {
      setCountry(countries[0].code);
    }
  }, [countries, country]);

  useEffect(() => {
    setEducation("");
    setOccupation("");
    setUrbanicity("");
    setStyle("");
  }, [country]);

  useEffect(() => {
    if (open) {
      setJobId(null);
      setJob(null);
      setError("");
      notified.current = false;
    }
  }, [open]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const data = await api.sampleJob(jobId);
        if (cancelled) return;
        setJob(data);
        if (data.status === "done" && !notified.current) {
          notified.current = true;
          toastRef.current.push(`已加入 ${data.added_count ?? data.added.length} 位玩家`, "success");
          onDoneRef.current();
        }
        if (data.status === "error" && !notified.current) {
          notified.current = true;
          toastRef.current.push(data.message || "抽样失败", "error");
        }
        if (data.status === "queued" || data.status === "running") {
          timer = window.setTimeout(poll, 850);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "读取进度失败");
          timer = window.setTimeout(poll, 1600);
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  const submit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await api.sample({
        country,
        age_min: ageMin ? Number(ageMin) : null,
        age_max: ageMax ? Number(ageMax) : null,
        gender,
        count,
        education: education ? [education] : [],
        occupation_group: occupation ? [occupation] : [],
        urbanicity,
        consumption_style: style ? [style] : [],
      });
      setJobId(result.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "抽样失败");
    } finally {
      setSubmitting(false);
    }
  };

  const close = () => {
    if (running) return;
    onClose();
  };

  const progress = job
    ? job.phase === "testing" && job.requested
      ? (job.tested / job.requested) * 100
      : job.status === "done"
        ? 100
        : 8
    : 0;

  return (
    <Modal
      open={open}
      onClose={close}
      title="从人口库抽取玩家"
      subtitle={`每位样本都会独立完成一次《${questionnaireName || "当前生效问卷"}》测验，结果与该玩家绑定。`}
      size="lg"
      closable={!running}
      footer={
        job && job.status !== "queued" && job.status !== "running" ? (
          <Button variant="primary" onClick={close}>完成</Button>
        ) : !job ? (
          <>
            <Button variant="ghost" onClick={close}>取消</Button>
            <Button variant="primary" icon="sparkles" loading={submitting} onClick={submit}>
              开始抽取 {count} 人
            </Button>
          </>
        ) : null
      }
    >
      {!job ? (
        <div className="sample-form">
          <div className="sample-form__row">
            <Field label="国家 / 人口版本" hint={selectedCountry ? selectedCountry.items[0]?.name : "使用 AudienceLib 默认授权人口"}>
              <select value={country} onChange={(event) => setCountry(event.target.value)}>
                {countries.map((item) => (
                  <option key={item.code} value={item.code}>{item.name} · {item.code}</option>
                ))}
              </select>
            </Field>
            <Field label="性别">
              <Segmented
                value={gender}
                onChange={setGender}
                options={[
                  { value: "", label: "不限" },
                  { value: "男", label: "男" },
                  { value: "女", label: "女" },
                ]}
              />
            </Field>
          </div>
          <div className="sample-form__row">
            <Field label="最低年龄">
              <input type="number" min={0} max={120} value={ageMin} onChange={(event) => setAgeMin(event.target.value)} placeholder="不限" />
            </Field>
            <Field label="最高年龄">
              <input type="number" min={0} max={120} value={ageMax} onChange={(event) => setAgeMax(event.target.value)} placeholder="不限" />
            </Field>
          </div>
          <details className="sample-more">
            <summary>更多人口筛选（可选）</summary>
            <div className="sample-more__grid">
              <Field label="城乡">
                <select value={urbanicity} onChange={(event) => setUrbanicity(event.target.value)}>
                  <option value="">不限</option>
                  {(facets.urbanicity || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </Field>
              <Field label="学历">
                <select value={education} onChange={(event) => setEducation(event.target.value)}>
                  <option value="">不限</option>
                  {(facets.education || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </Field>
              <Field label="职业大类">
                <select value={occupation} onChange={(event) => setOccupation(event.target.value)}>
                  <option value="">不限</option>
                  {(facets.occupation_group || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </Field>
              <Field label="消费风格">
                <select value={style} onChange={(event) => setStyle(event.target.value)}>
                  <option value="">不限</option>
                  {(facets.consumption_style || []).map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </Field>
            </div>
          </details>
          <div className="sample-count">
            <div className="sample-count__head">
              <Field label="单次抽取样本量" hint="单次最高 10000 人；每次抽样会消耗人口库额度，人数越多耗时和模型消耗越大。">
                <div className="range-row">
                  <input
                    type="range"
                    min={1}
                    max={10000}
                    value={count}
                    onChange={(event) => setCount(Number(event.target.value))}
                  />
                  <input
                    className="range-number"
                    type="number"
                    min={1}
                    max={10000}
                    value={count}
                    onChange={(event) => setCount(Math.max(1, Math.min(10000, Number(event.target.value) || 1)))}
                  />
                </div>
              </Field>
            </div>
            <div className="sample-count__quota">
              {selectedCountry?.sampling_quota ? (
                <>
                  <Icon name="tokens" size={15} />
                  本 Key 剩余抽样额度 <b>{selectedCountry.sampling_quota.remaining.toLocaleString()}</b> 人
                </>
              ) : (
                <>
                  <Icon name="info" size={15} />
                  额度信息将在抽样后由 AudienceLib 返回
                </>
              )}
            </div>
          </div>
          <div className="sample-note">
            <Icon name="clock" size={16} />
            <div>
              <b>预计耗时约 {Math.max(1, Math.round(count * 0.7 / 60))}–{Math.max(2, Math.ceil(count * 1.3 / 60))} 分钟。</b>
              <span>抽样先从 AudienceLib 拉取人物档案，再由 DeepSeek 以该人物身份逐题作答。每位玩家约 1–2 秒。</span>
            </div>
          </div>
          {count > 1000 ? (
            <div className="inline-warn">
              <Icon name="alert" size={16} />
              <span>本批会产生 {count.toLocaleString()} 次 93 题模型测验，预计持续数小时并消耗大量 token；请确认人口库额度和模型用量后分批执行。</span>
            </div>
          ) : null}
          {error ? <div className="inline-error"><Icon name="alert" size={16} /> {error}</div> : null}
        </div>
      ) : (
        <div className="sample-progress">
          <div className="sample-progress__head">
            <div>
              <div className="eyebrow">{job.status === "done" ? "COMPLETE" : "IN PROGRESS"}</div>
              <h3>{job.message}</h3>
            </div>
            <div className="sample-progress__count">
              <b>{job.tested}</b> / {job.requested}
            </div>
          </div>
          <ProgressBar value={progress} shimmer={running} height={10} />
          <div className="sample-progress__stages">
            <span className={job.phase !== "queued" ? "is-done" : ""}><i />抽样</span>
            <span className={job.phase === "testing" ? "is-active" : job.status === "done" ? "is-done" : ""}><i />MBTI 问卷</span>
            <span className={job.status === "done" ? "is-done" : ""}><i />绑定入库</span>
          </div>
          {job.people.length ? (
            <div className="sample-people">
              {job.people_total && job.people_total > job.people.length ? (
                <div className="sample-people__note">仅显示最近 {job.people.length} 人，共 {job.people_total} 人</div>
              ) : null}
              {job.people.map((person, index) => (
                <div className={`sample-person ${person.status}`} key={`${person.name}-${index}`}>
                  <span className="sample-person__name">{person.name}</span>
                  {person.mbti ? <TypeBadge type={person.mbti} size="sm" /> : <span className="sample-person__wait">{person.status === "failed" ? "失败" : "测验中…"}</span>}
                </div>
              ))}
            </div>
          ) : null}
          {job.status === "done" ? (
            <div className="sample-result">
              <div className="sample-result__icon"><Icon name="check" size={20} /></div>
              <div>
                <b>本批玩家已入库</b>
                <span>
                  {Object.entries(job.added_counts || job.added.reduce<Record<string, number>>((acc, item) => {
                    acc[item.mbti] = (acc[item.mbti] || 0) + 1;
                    return acc;
                  }, {})).map(([code, n]) => `${code} ×${n}`).join(" · ") || "无"}
                </span>
              </div>
            </div>
          ) : null}
          {job.errors.length ? (
            <div className="sample-errors">
              <b>{job.errors_total ?? job.errors.length} 条异常</b>
              {job.errors.slice(0, 3).map((item, index) => (
                <span key={index}>{item.name ? `${item.name}：` : ""}{item.error}</span>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
