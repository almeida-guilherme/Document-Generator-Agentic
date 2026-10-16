import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { PlusIcon, StatusPill } from "../components";
import { dateTime } from "../format";
import { usePolling } from "../usePolling";

export default function ProjectsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.runs().then(setRuns, (e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  usePolling(load, 3000, !!runs?.some((r) => r.status === "queued" || r.status === "running"));

  return (
    <main className="page">
      <div className="page-head row">
        <div className="page-head">
          <h1>Projects</h1>
          <p>Open a project or create a new one from a video.</p>
        </div>
        <Link to="/projects/new" className="btn btn-dark"><PlusIcon />New project</Link>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {runs === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="project-grid">
          <Link to="/projects/new" className="project-new">
            <span className="plus"><PlusIcon size={18} /></span>
            Create a new project
          </Link>
          {runs.map((run) => (
            <Link key={run.id} to={`/runs/${run.id}`} className="project-card">
              <div className="top">
                <span className="doc-icon" aria-hidden="true" />
                <StatusPill status={run.status} />
              </div>
              <div className="bottom">
                <span className="name">{run.name ?? run.process_name ?? run.video_name}</span>
                <span className="meta">
                  {run.template_name ?? "Pidi template"} · {dateTime(run.finished_at ?? run.created_at)}
                </span>
                {(run.status === "running" || run.status === "queued") && run.message && (
                  <span className="progress-msg">{run.message}</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
