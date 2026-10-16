import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, uploadRecording, type Run, type Template } from "../api";
import { STATUS_LABELS, bytes, dateTime } from "../format";
import { usePolling } from "../usePolling";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.wmv";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.runs().then(setRuns, (e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  usePolling(load, 3000, !!runs?.some((r) => r.status === "queued" || r.status === "running"));

  return (
    <>
      <Uploader />
      <section className="card">
        <h2>Your documents</h2>
        {error && <p className="error">{error}</p>}
        {runs === null ? (
          <p className="muted">Loading…</p>
        ) : runs.length === 0 ? (
          <p className="muted">Nothing here yet. Upload a screen recording above to create your first document.</p>
        ) : (
          <ul className="run-list">
            {runs.map((run) => (
              <li key={run.id}>
                <Link to={`/runs/${run.id}`} className="run-row">
                  <span className="run-title">
                    <strong>{run.process_name ?? run.video_name}</strong>
                    <span className="muted small">
                      {run.process_name ? `${run.video_name} · ` : ""}
                      {dateTime(run.created_at)}
                    </span>
                  </span>
                  <span className="run-progress muted small">
                    {run.status === "running" || run.status === "queued" ? run.message : ""}
                  </span>
                  <StatusBadge status={run.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

export function StatusBadge({ status }: { status: Run["status"] }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>;
}

function Uploader() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState("");

  useEffect(() => {
    api.templates().then(setTemplates, () => setTemplates([]));
  }, []);

  function choose(f: File | undefined) {
    setError(null);
    if (f) setFile(f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files[0]);
  }

  async function start() {
    if (!file) return;
    setError(null);
    setProgress(0);
    try {
      const run = await uploadRecording(file, templateId || null, setProgress);
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
  }

  const uploading = progress !== null;
  return (
    <section className="card">
      <h1>New document</h1>
      <p className="muted">
        Upload a screen recording of someone doing the process. Narration helps: explaining each step and its
        rules out loud gives a more complete document.
      </p>
      <div
        className={`dropzone${dragging ? " dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => !uploading && input.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
      >
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => choose(e.target.files?.[0])} />
        {file ? (
          <>
            <strong>{file.name}</strong>
            <span className="muted small">{bytes(file.size)} · click to choose another file</span>
          </>
        ) : (
          <>
            <strong>Drop a recording here, or click to choose one</strong>
            <span className="muted small">MP4, MOV, MKV, WebM, AVI or WMV</span>
          </>
        )}
      </div>
      <label className="template-choice">
        Document layout
        <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={uploading}>
          <option value="">Standard PDD</option>
          {templates.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.language})</option>)}
        </select>
        <span className="hint">
          {templates.length ? "Pick your company's template to write the document into it. " : "Use your company's own PDD format: "}
          <Link to="/templates">{templates.length ? "Manage templates" : "add a template"}</Link>
        </span>
      </label>
      {uploading && (
        <div className="upload-progress">
          <div className="bar"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          <span className="muted small">
            {progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Checking the video…"}
          </span>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button className="button primary" disabled={!file || uploading} onClick={start}>
          Generate document
        </button>
      </div>
    </section>
  );
}
