import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Template } from "../api";
import { bytes, dateTime } from "../format";

export default function TemplatesPage() {
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.templates().then(setTemplates, (e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const template = await api.uploadTemplate(file);
      navigate(`/templates/${template.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card">
        <h1>Company templates</h1>
        <p className="muted">
          Upload the Word document your company uses for PDDs. It is read once: its cover, styles and fixed text are
          kept, instructions and leftovers from other processes (example steps, screenshots, names) are removed, and
          the rest is filled for each recording.
        </p>
        <div
          className="dropzone"
          role="button"
          tabIndex={0}
          onClick={() => !busy && input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        >
          <input ref={input} type="file" accept=".docx" hidden
                 onChange={(e) => { setError(null); setFile(e.target.files?.[0] ?? null); }} />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="muted small">{bytes(file.size)} · click to choose another file</span>
            </>
          ) : (
            <>
              <strong>Click to choose a template</strong>
              <span className="muted small">Word document (.docx)</span>
            </>
          )}
        </div>
        {busy && <p className="muted small" aria-live="polite">Reading the template… this takes about half a minute.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button className="button primary" disabled={!file || busy} onClick={upload}>
            {busy ? "Reading the template…" : "Add template"}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>Your templates</h2>
        {templates === null ? (
          <p className="muted">Loading…</p>
        ) : templates.length === 0 ? (
          <p className="muted">No templates yet. Documents use the standard PDD layout until you add one.</p>
        ) : (
          <ul className="run-list">
            {templates.map((t) => (
              <li key={t.id}>
                <Link to={`/templates/${t.id}`} className="run-row">
                  <span className="run-title">
                    <strong>{t.name}</strong>
                    <span className="muted small">{t.language} · added {dateTime(t.created_at)}</span>
                  </span>
                  <span />
                  <span className="badge badge-done">Ready</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
