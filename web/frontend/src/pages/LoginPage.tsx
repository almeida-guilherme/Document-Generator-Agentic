import { useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App";
import { Logo } from "../components";

export default function LoginPage() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const isLogin = params.get("mode") !== "register";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function switchTo(mode: "login" | "register") {
    setError(null);
    setParams(mode === "register" ? { mode } : {}, { replace: true, state: location.state });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await (isLogin ? api.login(email, password) : api.register(name, email, password));
      setUser(user);
      navigate((location.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <header className="auth-header"><Logo to="/" large /></header>
      <main className="auth-main">
        <div className="auth-card">
          <div role="tablist" aria-label="Account access" className="tabs">
            <button type="button" role="tab" aria-selected={isLogin} onClick={() => switchTo("login")}>Log in</button>
            <button type="button" role="tab" aria-selected={!isLogin} onClick={() => switchTo("register")}>
              Create account
            </button>
          </div>

          <form onSubmit={submit}>
            <div className="intro">
              <h1>{isLogin ? "Welcome back" : "Create your account"}</h1>
              <p>{isLogin ? "Log in to see your projects." : "Start turning recordings into PDDs."}</p>
            </div>
            {!isLogin && (
              <div className="field">
                <label htmlFor="reg-name">Name</label>
                <input id="reg-name" type="text" placeholder="Your full name" autoComplete="name" value={name}
                       onChange={(e) => setName(e.target.value)} />
              </div>
            )}
            <div className="field">
              <label htmlFor="auth-email">Email</label>
              <input id="auth-email" type="email" placeholder="you@company.com" autoComplete="email" required
                     value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="auth-password">Password</label>
              <input id="auth-password" type="password" required minLength={isLogin ? undefined : 8}
                     placeholder={isLogin ? "Your password" : "Create a password (at least 8 characters)"}
                     autoComplete={isLogin ? "current-password" : "new-password"}
                     value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="btn btn-dark btn-lg btn-block" disabled={busy}>
              {busy ? "Please wait…" : isLogin ? "Log in" : "Create account"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
