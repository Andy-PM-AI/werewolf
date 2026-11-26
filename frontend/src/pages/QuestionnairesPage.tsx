import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import type { Questionnaire, QuestionnaireJob } from "../lib/types";
import { formatDate } from "../lib/format";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Modal,
  ProgressBar,
  SectionHead,
  Spinner,
  StatTile,
  useToast,
} from "../components/Ui";
import { Icon } from "../components/Icons";

export function QuestionnairesPage({ onNavigate }: { onNavigate: (path: string) => void }) {
  const toast = useToast();
  const [items, setItems] = useState<Questionnaire[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadName, setUploadName] = useState("");
  const [uploadText, setUploadText] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Questionnaire | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [job, setJob] = useState<QuestionnaireJob | null>(null);
  const [starting, setStarting] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.questionnaires();
      setItems(data.items);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "读取问卷失败", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!job || (job.status !== "running")) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.questionnaireJob(job.id);
        setJob(next);
        if (next.status === "done" || next.status === "error") {
          load();
        }
      } catch {
        // The job may have been restarted; keep the last state visible.
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, load]);

  const active = items.find((item) => item.is_active);
  const totals = useMemo(() => ({
    count: items.length,
    questions: items.reduce((sum, item) => sum + (item.question_count || 0), 0),
    covered: active?.tested || 0,
    total: active?.total || 0,
  }), [items, active]);

  const toggleSelected = (id: string) => {
    setSelected((current) => {
      if (current.includes(id)) return current.filter((x) => x !== id);
      if (current.length >= 2) {
        toast.push("一次只能选择两套问卷进行对比", "info");
        return current;
      }
      return [...current, id];
    });
  };

  const addToCompare = (id: string) => {
    setSelected((current) => {
      if (current.includes(id)) return current;
      if (current.length >= 2) {
        toast.push("一次只能选择两套问卷进行对比，请先取消一套", "info");
        return current;
      }
      return [...current, id];
    });
  };

  const activate = async (id: string) => {
    try {
      await api.activateQuestionnaire(id);
      toast.push("已切换当前生效问卷", "success");
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "切换失败", "error");
    }
  };

  const startTest = async (item: Questionnaire) => {
    setStarting(item.id);
    try {
      const result = await api.testQuestionnaire(item.id);
      const next = await api.questionnaireJob(result.job_id);
      setJob(next);
      if (next.status === "running") toast.push(`已开始测试《${item.name}》`, "info");
      else toast.push(next.message, "success");
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "启动测试失败", "error");
    } finally {
      setStarting("");
    }
  };

  const readFile = async (file?: File | null) => {
    if (!file) return;
    setUploadError("");
    try {
      const text = await file.text();
      JSON.parse(text);
      setUploadText(text);
      const parsed = JSON.parse(text) as { name?: string };
      if (parsed.name) setUploadName(parsed.name);
    } catch {
      setUploadError("文件不是合法的 JSON");
      setUploadText("");
    }
  };

  const upload = async () => {
    setUploadError("");
    let definition: Record<string, unknown>;
    try {
      definition = JSON.parse(uploadText);
    } catch {
      setUploadError("请选择合法的问卷 JSON 文件");
      return;
    }
    setUploading(true);
    try {
      await api.uploadQuestionnaire(definition, uploadName.trim() || undefined);
      toast.push("问卷已上传", "success");
      setUploadOpen(false);
      setUploadText("");
      setUploadName("");
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const downloadTemplate = async () => {
    try {
      const { definition } = await api.questionnaireTemplate();
      const blob = new Blob([JSON.stringify(definition, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "werewolf-questionnaire-template.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "下载模板失败", "error");
    }
  };

  const downloadConversionPrompt = async () => {
    try {
      const data = await api.questionnaireConversionPrompt();
      const blob = new Blob([data.content], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = data.filename || "questionnaire-conversion-prompt.md";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "下载转换 Prompt 失败", "error");
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.deleteQuestionnaire(deleteTarget.id);
      toast.push("问卷已删除", "success");
      setDeleteTarget(null);
      setSelected((current) => current.filter((id) => id !== deleteTarget.id));
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "删除失败", "error");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page questionnaire-page">
      <div className="page-head">
        <div>
          <button type="button" className="back-link" onClick={() => onNavigate("/players")}>
            <Icon name="arrowLeft" size={15} /> 玩家库
          </button>
          <div className="eyebrow">QUESTIONNAIRE LAB · 问卷实验</div>
          <h1 className="page-title">问卷管理</h1>
          <p className="page-desc">
            每套问卷独立保存每位玩家的结果。当前生效问卷决定玩家库展示、抽样默认测验和后续模拟使用的人格。
          </p>
        </div>
        <div className="page-actions">
          <Button variant="ghost" icon="arrowUpRight" onClick={downloadTemplate}>下载模板</Button>
          <Button variant="primary" icon="plus" onClick={() => setUploadOpen(true)}>上传新问卷</Button>
          <Button
            variant="secondary"
            icon="chart"
            disabled={selected.length !== 2}
            onClick={() => onNavigate(`/questionnaires/compare/${selected[0]}/${selected[1]}`)}
          >
            对比选中的 2 套问卷
          </Button>
        </div>
      </div>

      <div className="stat-row">
        <StatTile label="问卷总数" value={items.length} hint={`当前生效：${active?.name || "—"}`} icon="layers" tone="ochre" />
        <StatTile label="生效问卷覆盖率" value={active ? `${Math.round((active.coverage || 0) * 100)}%` : "—"} hint={active ? `${active.tested} / ${active.total} 人` : "尚无问卷"} icon="chart" tone="violet" />
        <StatTile label="题库规模" value={`${totals.questions.toLocaleString()} 题`} hint="所有问卷题数合计" icon="book" />
        <StatTile label="已选对比" value={`${selected.length} / 2`} hint="只能选择两套问卷" icon="grid" />
      </div>

      {job ? (
        <section className="questionnaire-job">
          <div className="questionnaire-job__head">
            <div>
              <b>问卷测试任务 · {job.status === "running" ? "运行中" : job.status === "done" ? "已完成" : "出错"}</b>
              <span>{job.message}</span>
            </div>
            <span>{job.tested} / {job.total} · 失败 {job.failed}</span>
          </div>
          <ProgressBar value={job.tested + job.failed} max={Math.max(1, job.total)} height={9} tone="ochre" shimmer={job.status === "running"} />
          <p>已测试完成的玩家会跳过；任务只处理开始时没有该问卷结果的玩家。</p>
          {job.errors?.length ? <div className="inline-error"><Icon name="alert" size={15} /> {job.errors[0].name ? `${job.errors[0].name}：` : ""}{job.errors[0].error}</div> : null}
        </section>
      ) : null}

      <section className="questionnaire-card">
        <SectionHead
          eyebrow="LIBRARY"
          title="问卷列表"
          desc="内置第一版问卷是模板，不能删除；新上传问卷可使用该模板格式。"
          actions={<span className="section-progress">{loading ? "读取中…" : `${items.length} 套问卷`}</span>}
        />
        {loading && !items.length ? (
          <div className="panel-loading"><Spinner size={24} /><span>正在读取问卷…</span></div>
        ) : items.length === 0 ? (
          <EmptyState icon="layers" title="还没有问卷" desc="上传第一套问卷，或等待内置问卷初始化。" />
        ) : (
          <div className="questionnaire-table-wrap">
            <table className="questionnaire-table">
              <thead>
                <tr>
                  <th>对比</th>
                  <th>问卷名称</th>
                  <th>题数</th>
                  <th>创建时间</th>
                  <th>上传用户</th>
                  <th>覆盖率</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className={item.is_active ? "is-active" : ""}>
                    <td>
                      <button
                        type="button"
                        className={`compare-check ${selected.includes(item.id) ? "is-checked" : ""}`}
                        onClick={() => toggleSelected(item.id)}
                        aria-label={`选择 ${item.name} 进行对比`}
                      >
                        {selected.includes(item.id) ? <Icon name="check" size={12} /> : null}
                      </button>
                    </td>
                    <td>
                      <div className="questionnaire-name">
                        <b>{item.name}</b>
                        <span>{item.version || "1.0"}{item.is_builtin ? " · 内置模板" : ""}{item.is_active ? " · 当前生效" : ""}</span>
                      </div>
                    </td>
                    <td>{item.question_count} 题 · {item.response_type === "likert5" ? "五度" : "A/B"} · {({ pole_majority: "多数决", dimension_bands: "维度分段", total_bands: "总分分段", highest_dimension: "最高维度" } as Record<string, string>)[item.scoring_mode || "pole_majority"] || item.scoring_mode}</td>
                    <td>{formatDate(item.created_at)}</td>
                    <td>{item.created_by || "—"}</td>
                    <td>
                      <div className="questionnaire-coverage">
                        <div className="questionnaire-coverage__bar"><span style={{ width: `${(item.coverage || 0) * 100}%` }} /></div>
                        <b>{Math.round((item.coverage || 0) * 100)}%</b>
                        <span>{item.tested} / {item.total}</span>
                      </div>
                    </td>
                    <td>
                      <div className="questionnaire-actions">
                        <Button variant="ghost" size="sm" disabled={item.is_active} onClick={() => activate(item.id)}>设为生效</Button>
                        <Button variant="secondary" size="sm" icon="play" loading={starting === item.id} disabled={item.tested >= item.total} onClick={() => startTest(item)}>测试未测玩家</Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={selected.includes(item.id)}
                          onClick={() => addToCompare(item.id)}
                        >
                          {selected.includes(item.id) ? "已加入对比" : "加入对比"}
                        </Button>
                        <Button variant="danger" size="sm" icon="trash" disabled={Boolean(item.is_builtin)} onClick={() => setDeleteTarget(item)}>删除</Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Modal
        open={uploadOpen}
        onClose={() => !uploading && setUploadOpen(false)}
        title="上传新问卷"
        subtitle="支持 JSON 格式。可先下载当前 MBTI 93 题作为模板，按同样结构修改题目和维度。"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setUploadOpen(false)} disabled={uploading}>取消</Button>
            <Button variant="primary" icon="plus" loading={uploading} disabled={!uploadText} onClick={upload}>上传问卷</Button>
          </>
        }
      >
        <div className="questionnaire-upload">
          <Field label="问卷文件（JSON）" hint="最大 2MB；支持 A/B 二选一或 1–5 五度量表；选项可映射维度极点，也可用 values/points 提供数值。">
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              onChange={(event) => readFile(event.target.files?.[0])}
            />
          </Field>
          <Field label="显示名称（可选）" hint="留空则使用 JSON 里的 name。">
            <input value={uploadName} onChange={(event) => setUploadName(event.target.value)} placeholder="例如：大五人格 60 题" />
          </Field>
          <div className="questionnaire-format">
            <b>支持格式</b>
            <p>问卷 JSON 需要包含 name、response_type、dimensions、questions、scoring。response_type 可为 binary（A/B）或 likert5（1–5 五度量表）；选项可写 scores（映射维度极点）、values（维度数值）或 points（总分）；具体计分由 scoring.mode 决定。</p>
            <p>当前 MBTI 第一版是 binary 模板，可直接下载后修改题数、维度和 type_names；五度量表请把 response_type 设为 likert5，并提供 1–5 五个选项。</p>
            <p>计分支持 pole_majority（极点多数决）、dimension_bands（维度分段）、total_bands（总分分段）和 highest_dimension（最高维度）；具体结构见下载的转换 Prompt。</p>
            <div className="questionnaire-format__actions">
              <Button variant="secondary" size="sm" icon="book" onClick={downloadConversionPrompt}>
                下载 AI 转换 Prompt（.md）
              </Button>
              <span>用于让 AI 把 HTML / Word / PDF 问卷转换成这里的 JSON 格式。</span>
            </div>
          </div>
          {uploadError ? <div className="inline-error"><Icon name="alert" size={15} /> {uploadError}</div> : null}
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除问卷"
        message={<>确定删除 <b>{deleteTarget?.name}</b>？该问卷下所有玩家的测试结果也会被删除，且不可撤销。</>}
        confirmText={deleting ? "删除中…" : "删除"}
        danger
        onCancel={() => setDeleteTarget(null)}
        onConfirm={remove}
      />
    </div>
  );
}
