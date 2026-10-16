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

  if (error && !template) return <section className="card"><p className="error">{error}</p><Link to="/templates">Back</Link></section>;
  if (!template) return <p className="muted">Loading…</p>;

  const removed = template.blocks.filter((b) => b.action === "remove");
  const filled = template.blocks.filter((b) => TEMPLATE_ACTIONS[b.action]?.tone === "fill" && b.kind !== "steps");

  return (
    <>
      <Link to="/templates" className="back">← All templates</Link>
      <section className="card">
        <h1>{template.name}</h1>
        <p className="muted small">{template.language} · added {dateTime(template.created_at)}</p>
        <dl className="stats">
          <div><dt>Parts filled per process</dt><dd>{filled.length}</dd></div>
          <div><dt>Removed</dt><dd>{removed.length}</dd></div>
          <div><dt>Placeholders</dt><dd>{template.placeholders.length}</dd></div>
          <div><dt>Steps written as</dt><dd className="mono">{template.step_label}…</dd></div>
        </dl>
        <p className="small muted" style={{ marginTop: 16 }}>
          Anything the recording doesn't tell (contacts, versions, volumes…) is written as{" "}
          <mark>{template.missing_label}</mark> so you can complete it.
        </p>
      </section>

      {template.placeholders.length > 0 && (
        <section className="card">
          <h2>Placeholders</h2>
          <ul className="plain">
            {template.placeholders.map((p) => (
              <li key={p.text}><code>{p.text}</code> <span className="muted small">— {p.meaning}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>How the template is used</h2>
        <p className="muted small">Every part of the template, in order, with what happens to it.</p>
        <div className="table-scroll">
          <table className="blocks">
            <thead><tr><th>Part of the template</th><th>What happens</th></tr></thead>
            <tbody>
              {template.blocks.map((b) => {
                const action = TEMPLATE_ACTIONS[b.action] ?? { label: b.action, tone: "keep" };
                return (
                  <tr key={`${b.kind}-${b.index}`} className={`block-${action.tone}${b.kind === "heading" ? " block-heading" : ""}`}>
                    <td>
                      {b.kind === "table" && <span className="muted small">Table: </span>}
                      {b.kind === "steps" ? <em>New: the detailed steps</em> : b.text || <span className="muted">(empty)</span>}
                    </td>
                    <td>
                      <span className={`tag tag-${action.tone}`}>{action.label}</span>
                      {(b.purpose || b.reason) && <div className="muted small">{b.purpose || b.reason}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="danger-zone">
        <button className="button ghost danger" onClick={remove}>Delete this template</button>
      </div>
    </>
  );
}
