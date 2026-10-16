import { useEffect, useState, type FormEvent } from "react";
import { api, type Keys } from "../api";
import { useAuth } from "../App";
import { initials } from "../components";

export default function AccountPage() {
  const { user } = useAuth();

  if (!user) return null;
  return (
    <main className="page medium">
      <div className="page-head">
        <h1>Account</h1>
        <p>Your info, password and connected APIs.</p>
      </div>
      <InfoSection />
      <PasswordSection />
      <KeysSection />
    </main>
  );
}

function useStatus() {
  const [status, setStatus] = useState<{ ok?: string; error?: string }>({});
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<string>) {
    setBusy(true);
    setStatus({});
    try {
      setStatus({ ok: await action() });
    } catch (e) {
      setStatus({ error: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  const message = status.ok ? <p className="notice-ok" role="status">{status.ok}</p>
    : status.error ? <p className="error" role="alert">{status.error}</p> : null;
  return { busy, run, message };
}

function InfoSection() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const { busy, run, message } = useStatus();

  function save(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      setUser(await api.updateProfile(name, email));
      return "Saved.";
    });
  }

  if (!user) return null;
  return (
    <form className="card" aria-labelledby="sec-info" onSubmit={save}>
      <div className="section-head">
        <span className="avatar large" aria-hidden="true">{initials(user)}</span>
        <h2 id="sec-info">Your info</h2>
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="ac-name">Name</label>
          <input id="ac-name" type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ac-email">Current email</label>
          <input id="ac-email" type="email" autoComplete="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
      </div>
      {message}
      <div className="actions"><button className="btn btn-dark" disabled={busy}>Save changes</button></div>
    </form>
  );
}

function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const { busy, run, message } = useStatus();

  function save(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      if (next !== confirm) throw new Error("The new passwords don't match.");
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      return "Password updated. Other devices were logged out.";
    });
  }

  return (
    <form className="card" aria-labelledby="sec-pass" onSubmit={save}>
      <h2 id="sec-pass">Change password</h2>
      <div className="field">
        <label htmlFor="ac-pass-current">Current password</label>
        <input id="ac-pass-current" type="password" autoComplete="current-password" required value={current}
               onChange={(e) => setCurrent(e.target.value)} />
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="ac-pass-new">New password</label>
          <input id="ac-pass-new" type="password" autoComplete="new-password" required minLength={8} value={next}
                 onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ac-pass-confirm">Confirm new password</label>
          <input id="ac-pass-confirm" type="password" autoComplete="new-password" required minLength={8}
                 value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
      </div>
      {message}
      <div className="actions"><button className="btn btn-outline" disabled={busy}>Update password</button></div>
    </form>
  );
}

function KeysSection() {
  const [keys, setKeys] = useState<Keys | null>(null);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const { busy, run, message } = useStatus();

  useEffect(() => {
    api.keys().then(setKeys, () => setKeys({ keys: [], server_key: false }));
  }, []);

  function connect(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api.addKey(name, key);
      setKeys(await api.keys());
      setName("");
      setKey("");
      return "API connected.";
    });
  }

  function remove(id: string, label: string) {
    if (!confirm(`Remove "${label}"? Projects that haven't started yet with it will fail.`)) return;
    run(async () => {
      await api.removeKey(id);
      setKeys(await api.keys());
      return "API removed.";
    });
  }

  return (
    <section className="card" aria-labelledby="sec-api">
      <div className="card-head">
        <h2 id="sec-api">Connected APIs</h2>
        <p>Pidi uses your own API keys to process videos. Pick one when you create a project.</p>
      </div>

      {keys?.keys.map((k) => (
        <div key={k.id} className="key-row">
          <div className="who">
            <span className="dot" aria-hidden="true" />
            <div>
              <div className="label">OpenAI · {k.name}</div>
              <div className="hint">{k.hint}</div>
            </div>
          </div>
          <button type="button" className="btn btn-danger-text" disabled={busy} onClick={() => remove(k.id, k.name)}>
            Remove
          </button>
        </div>
      ))}
      {keys && keys.keys.length === 0 && (
        <p className="subtle small">
          {keys.server_key
            ? "No key of your own yet: projects run on the Pidi server key until you connect one."
            : "No API connected yet. Connect one to run projects."}
        </p>
      )}

      <form className="divider" onSubmit={connect}>
        <h3>Connect an API</h3>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="ac-provider">Provider</label>
            <select id="ac-provider" defaultValue="openai">
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="ac-keyname">Name</label>
            <input id="ac-keyname" type="text" placeholder="e.g. Work key" maxLength={60} value={name}
                   onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="ac-key">API key</label>
          <input id="ac-key" type="password" placeholder="Paste your API key" autoComplete="off" required value={key}
                 onChange={(e) => setKey(e.target.value)} />
        </div>
        {message}
        <div className="actions"><button className="btn btn-dark" disabled={busy}>{busy ? "Checking the key…" : "Connect API"}</button></div>
      </form>
    </section>
  );
}
