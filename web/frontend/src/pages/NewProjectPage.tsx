import { useEffect, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, uploadRecording, type Keys, type Template } from "../api";
import { UploadIcon } from "../components";
import { bytes } from "../format";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v,.wmv";
const SERVER_KEY = "server";

export default function NewProjectPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [keys, setKeys] = useState<Keys | null>(null);
  const [keyId, setKeyId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.templates().then(setTemplates, () => setTemplates([]));
    api.keys().then((k) => {
      setKeys(k);
      // The newest own key first; the server key only when there is no own key.
      setKeyId(k.keys.length ? k.keys[k.keys.length - 1].id : k.server_key ? SERVER_KEY : "");
    }, (e) => setError(e.message));
  }, []);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Choose the video of the process first.");
      return;
    }
    setError(null);
    setProgress(0);
    try {
      const run = await uploadRecording(file, {
        name, templateId: templateId || null, apiKeyId: keyId === SERVER_KEY ? null : keyId,
      }, setProgress);
      navigate(`/runs/${run.id}`);
    } catch (err) {
      setError((err as Error).message);
      setProgress(null);
    }
  }

  const uploading = progress !== null;
  const noKey = keys !== null && !keyId;

  return (
    <main className="page narrow">
      <div className="page-head" style={{ gap: 12 }}>
        <Link to="/" className="back">← Back to projects</Link>
        <h1>New project</h1>
        <p>Upload the recording and Pidi will turn it into a PDD.</p>
      </div>

      <form className="card form" style={{ padding: 36, gap: 28 }} onSubmit={submit}>
        <div className="field">
          <label htmlFor="np-name">Project name</label>
          <input id="np-name" type="text" placeholder="e.g. Invoice approval in SAP" value={name}
                 onChange={(e) => setName(e.target.value)} maxLength={120} />
        </div>

        <div className="field">
          <label htmlFor="np-template">PDD document template</label>
          <p className="hint">The structure your document will follow.</p>
          <select id="np-template" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">Pidi template (default)</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.language})</option>)}
          </select>
          <p className="after">Using your company's own format? <Link to="/templates">Add a template</Link></p>
        </div>

        <div className="field">
          <label htmlFor="np-video">Video</label>
          <p className="hint">A screen recording of the process. Narration is optional but helps.</p>
          <label htmlFor="np-video" className={`dropzone${dragging ? " dragging" : ""}`}
                 onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                 onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <span className="dropzone-icon"><UploadIcon /></span>
            {file ? (
              <>
                <strong>{file.name}</strong>
                <span className="subtle small">{bytes(file.size)} · <span className="u">choose another</span></span>
              </>
            ) : (
              <>
                <strong>Drop your video here or <span className="u">browse</span></strong>
                <span className="subtle small">MP4, MOV, MKV, WebM, AVI or WMV</span>
              </>
            )}
          </label>
          <input id="np-video" className="sr-only" type="file" accept={ACCEPT} disabled={uploading}
                 onChange={(e) => { setError(null); setFile(e.target.files?.[0] ?? null); }} />
          {uploading && (
            <div className="progress" style={{ marginTop: 14 }}>
              <div className="bar"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
              <span className="subtle small" aria-live="polite">
                {progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Checking the video…"}
              </span>
            </div>
          )}
        </div>

        <div className="field">
          <label htmlFor="np-api">API used</label>
          <p className="hint">Which of your connected APIs will run this project.</p>
          <select id="np-api" value={keyId} onChange={(e) => setKeyId(e.target.value)} disabled={noKey}>
            {noKey && <option value="">No API connected</option>}
            {keys?.keys.map((k) => <option key={k.id} value={k.id}>OpenAI · {k.name} ({k.hint})</option>)}
            {keys?.server_key && <option value={SERVER_KEY}>Pidi server key</option>}
          </select>
          <p className="after">
            {noKey ? "Connect your API key to run projects. " : "Need another one? "}
            <Link to="/account">Connect an API</Link>
          </p>
        </div>

        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions" style={{ paddingTop: 4 }}>
          <Link to="/" className="btn btn-outline">Cancel</Link>
          <button className="btn btn-dark" disabled={uploading || noKey || keys === null}>Create a new project</button>
        </div>
      </form>
    </main>
  );
}
