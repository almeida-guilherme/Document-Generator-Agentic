import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type TemplateDetail } from "../api";
import { TEMPLATE_ACTIONS, dateTime } from "../format";

export default function TemplatePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.template(id).then(setTemplate, (e: ApiError) =>
      setError(e.status === 404 ? "This template doesn't exist." : e.message));
  }, [id]);

  async function remove() {
    if (!confirm("Delete this template? Documents already made with it are not affected.")) return;
    try {
      await api.removeTemplate(id);
      navigate("/templates");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !template) {
    return <main className="page wide"><p className="error">{error}</p><Link to="/templates" className="back">← All templates</Link></main>;
  }
  if (!template) return <main className="page wide"><p className="muted">Loading…</p></main>;

  const removed = template.blocks.filter((b) => b.action === "remove");
  const filled = template.blocks.filter((b) => TEMPLATE_ACTIONS[b.action]?.tone === "fill" && b.kind !== "steps");

  return (
    <main className="page wide">
      <Link to="/templates" className="back">← All templates</Link>
      <section className="card">
        <div className="page-head">
          <h1 style={{ fontSize: 34 }}>{template.name}</h1>
          <p className="subtle small">{template.language} · added {dateTime(template.created_at)}</p>
        </div>
        <dl className="stats">
          <div><dt>Parts filled per process</dt><dd>{filled.length}</dd></div>
          <div><dt>Removed</dt><dd>{removed.length}</dd></div>
          <div><dt>Placeholders</dt><dd>{template.placeholders.length}</dd></div>
          <div><dt>Steps written as</dt><dd className="mono">{template.step_label}…</dd></div>
        </dl>
        <p className="small muted">
          Anything the recording doesn't tell (contacts, versions, volumes…) is written as{" "}
          <mark>{template.missing_label}</mark> so you can complete it.
        </p>
      </section>

      {template.placeholders.length > 0 && (
        <section className="card">
          <h2>Placeholders</h2>
          <ul className="plain">
            {template.placeholders.map((p) => (
              <li key={p.text}><code>{p.text}</code> <span className="subtle small">— {p.meaning}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>How the template is used</h2>
          <p>Every part of the template, in order, with what happens to it.</p>
        </div>
        <div className="table-scroll">
          <table className="blocks">
            <thead><tr><th>Part of the template</th><th>What happens</th></tr></thead>
            <tbody>
              {template.blocks.map((b) => {
                const action = TEMPLATE_ACTIONS[b.action] ?? { label: b.action, tone: "keep" };
                return (
                  <tr key={`${b.kind}-${b.index}`} className={`block-${action.tone}${b.kind === "heading" ? " block-heading" : ""}`}>
                    <td>
                      {b.kind === "table" && <span className="subtle small">Table: </span>}
                      {b.kind === "steps" ? <em>New: the detailed steps</em> : b.text || <span className="muted">(empty)</span>}
                    </td>
                    <td>
                      <span className={`tag tag-${action.tone}`}>{action.label}</span>
                      {(b.purpose || b.reason) && <div className="subtle">{b.purpose || b.reason}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="end">
        <button className="btn btn-danger-text" onClick={remove}>Delete this template</button>
      </div>
    </main>
  );
}
