import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Template } from "../api";
import { UploadIcon } from "../components";
import { bytes, dateTime } from "../format";

export default function TemplatesPage() {
  const navigate = useNavigate();
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
    <main className="page medium">
      <div className="page-head">
        <h1>Templates</h1>
        <p>Use your company's own PDD format instead of the default one.</p>
      </div>
      <section className="card">
        <div className="card-head">
          <h2>Add a template</h2>
          <p>
            Upload the Word document your company uses for PDDs. It is read once: its cover, styles and fixed text are
            kept, instructions and leftovers from other processes (example steps, screenshots, names) are removed, and
            the rest is filled for each recording.
          </p>
        </div>
        <label htmlFor="tpl-file" className="dropzone">
          <span className="dropzone-icon"><UploadIcon /></span>
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="subtle small">{bytes(file.size)} · <span className="u">choose another</span></span>
            </>
          ) : (
            <>
              <strong>Choose a template or <span className="u">browse</span></strong>
              <span className="subtle small">Word document (.docx)</span>
            </>
          )}
        </label>
        <input id="tpl-file" className="sr-only" type="file" accept=".docx" disabled={busy}
               onChange={(e) => { setError(null); setFile(e.target.files?.[0] ?? null); }} />
        {busy && <p className="subtle small" aria-live="polite">Reading the template… this takes about half a minute.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions">
          <button className="btn btn-dark" disabled={!file || busy} onClick={upload}>
            {busy ? "Reading the template…" : "Add template"}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>Your templates</h2>
        {templates === null ? (
          <p className="muted">Loading…</p>
        ) : templates.length === 0 ? (
          <p className="subtle">No templates yet. Projects use the default Pidi model until you add one.</p>
        ) : (
          <ul className="list">
            {templates.map((t) => (
              <li key={t.id}>
                <Link to={`/templates/${t.id}`} className="list-row">
                  <span className="title">
                    <strong>{t.name}</strong>
                    <span className="subtle small">{t.language} · added {dateTime(t.created_at)}</span>
                  </span>
                  <span className="pill pill-done">Ready</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
