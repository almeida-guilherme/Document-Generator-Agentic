import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type ProcessModel, type Run } from "../api";
import { StatusPill } from "../components";
import { INPUT_KINDS, REQUIREMENT_LABELS, STAGE_LABELS, dateTime, duration } from "../format";
import { usePolling } from "../usePolling";

export default function RunPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<Run | null>(null);
  const [model, setModel] = useState<ProcessModel | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.run(id).then(setRun, (e: ApiError) => setError(e.status === 404 ? "This project doesn't exist." : e.message));
  }, [id]);
  useEffect(load, [load]);
  const active = run?.status === "queued" || run?.status === "running";
  usePolling(load, 2000, active);

  useEffect(() => {
    if (run?.status === "done" && !model) api.model(id).then(setModel, (e) => setError(e.message));
  }, [run?.status, id, model]);

  async function retry() {
    setRun(await api.retry(id));
  }

  async function remove() {
    if (!confirm("Delete this project, its document, screenshots and the uploaded recording?")) return;
    try {
      await api.remove(id);
      navigate("/");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !run) {
    return <main className="page wide"><p className="error">{error}</p><Link to="/" className="back">← Back to projects</Link></main>;
  }
  if (!run) return <main className="page wide"><p className="muted">Loading…</p></main>;

  return (
    <main className="page wide">
      <Link to="/" className="back">← Back to projects</Link>
      <section className="card">
        <div className="run-head">
          <div className="page-head">
            <h1>{run.name ?? run.process_name ?? run.video_name}</h1>
            <p className="subtle small">
              {run.video_name} · uploaded {dateTime(run.created_at)} · {run.template_name ?? "Pidi template"}
            </p>
          </div>
          <StatusPill status={run.status} />
        </div>

        {active && <Stages run={run} />}

        {run.status === "failed" && (
          <div className="notice notice-error">
            <p>{run.error}</p>
            <button className="btn btn-dark" onClick={retry}>Retry</button>
          </div>
        )}

        {run.status === "done" && (
          <>
            <div><a className="btn btn-dark btn-lg" href={api.documentUrl(run.id)} download>Download Word document</a></div>
            {run.summary && (
              <dl className="stats">
                <div><dt>Steps</dt><dd>{run.summary.steps ?? "–"}</dd></div>
                <div><dt>Screenshots</dt><dd>{run.summary.screenshots ?? "–"}</dd></div>
                <div><dt>Recorded time</dt><dd>{duration(run.summary.recorded_seconds)}</dd></div>
                <div><dt>Cost</dt><dd>{run.summary.cost_usd != null ? `$${run.summary.cost_usd.toFixed(2)}` : "–"}</dd></div>
              </dl>
            )}
            {!!run.summary?.warnings.length && (
              <div className="notice">
                <strong>Worth checking</strong>
                <ul>{run.summary.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            )}
          </>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      {model && <ModelView model={model} />}

      {!active && (
        <div className="end">
          <button className="btn btn-danger-text" onClick={remove}>Delete this project</button>
        </div>
      )}
    </main>
  );
}

function Stages({ run }: { run: Run }) {
  // "reuse_run" stands for the three recording stages at once (a run made from an earlier one's captions).
  const current = run.stage === "reuse_run" ? run.stages.indexOf("transcribe") : run.stages.indexOf(run.stage ?? "");
  return (
    <div className="stages" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <ol>
        {run.stages.map((key, i) => {
          const state = run.status === "queued" ? "pending" : i < current ? "done" : i === current ? "current" : "pending";
          return (
            <li key={key} className={`stage stage-${state}`}>
              <span className="stage-dot" aria-hidden />
              {STAGE_LABELS[key] ?? key}
            </li>
          );
        })}
      </ol>
      <p className="muted small" aria-live="polite">
        {run.message ?? (run.status === "queued" ? "Waiting for the previous projects to finish" : "Starting")}
      </p>
      <p className="subtle small">
        A five-minute recording takes a few minutes. You can leave this page; the document keeps being made.
      </p>
    </div>
  );
}

function ModelView({ model }: { model: ProcessModel }) {
  const applications = [...new Set(model.as_is.map((s) => s.application).filter(Boolean))];
  const exceptions = [
    ...model.business_exceptions.map((e) => ({ ...e, type: "Business" })),
    ...model.system_exceptions.map((e) => ({ ...e, type: "System" })),
  ];
  return (
    <>
      <section className="card">
        <h2>Overview</h2>
        <p>{model.project_proposal}</p>
        <dl className="facts">
          <dt>Applications</dt>
          <dd>{applications.length ? applications.map((a) => <span key={a} className="chip">{a}</span>) : "Not identified"}</dd>
          <dt>Inputs</dt>
          <dd>
            {model.inputs.length ? (
              <ul className="plain">
                {model.inputs.map((input) => (
                  <li key={input.name}>
                    {input.name} <span className="subtle small">({INPUT_KINDS[input.kind]}{input.source ? `, from ${input.source}` : ""})</span>
                  </li>
                ))}
              </ul>
            ) : "Not identified"}
          </dd>
        </dl>
      </section>

      <section className="card">
        <h2>Steps</h2>
        <ol className="steps">
          {model.as_is.map((step) => (
            <li key={step.number} className="step">
              <div className="step-text">
                <div className="step-meta">
                  <span className="step-number">{step.number}</span>
                  {step.application && <span className="chip">{step.application}</span>}
                  {step.time && <span className="subtle small">at {step.time}</span>}
                </div>
                <p>{step.instruction}</p>
                {step.decision && <p className="decision"><strong>Decision:</strong> {step.decision}</p>}
              </div>
              {step.image_url ? (
                <a href={step.image_url} target="_blank" rel="noreferrer" className="step-shot">
                  <img src={step.image_url} alt={`Screenshot of step ${step.number}`} loading="lazy" />
                </a>
              ) : (
                <div className="step-shot empty subtle small">No screenshot</div>
              )}
            </li>
          ))}
        </ol>
      </section>

      {model.requirements.length > 0 && (
        <section className="card">
          <h2>Business rules & requirements</h2>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Type</th><th>Description</th></tr></thead>
              <tbody>
                {model.requirements.map((r, i) => (
                  <tr key={i}><td>{REQUIREMENT_LABELS[r.category] ?? r.category}</td><td>{r.description}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {exceptions.length > 0 && (
        <section className="card">
          <h2>Exceptions</h2>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Type</th><th>Exception</th><th>When</th><th>What to do</th></tr></thead>
              <tbody>
                {exceptions.map((e, i) => (
                  <tr key={i}><td>{e.type}</td><td>{e.name}</td><td>{e.action}</td><td>{e.action_to_be_taken}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
