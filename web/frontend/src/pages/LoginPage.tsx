import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../App";

export default function LoginPage({ mode }: { mode: "login" | "register" }) {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await (isLogin ? api.login(email, password) : api.register(email, password));
      setUser(user);
      navigate((location.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
        <div className="brand auth-brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          Document Generator
        </div>
        <h1>{isLogin ? "Log in" : "Create an account"}</h1>
        <p className="muted">
          Turn a screen recording of a process into a Process Design Document for your RPA team.
        </p>
        <label>
          Email
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            minLength={isLogin ? undefined : 8}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {!isLogin && <span className="hint">At least 8 characters.</span>}
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="button primary" disabled={busy}>
          {busy ? "Please wait…" : isLogin ? "Log in" : "Create account"}
        </button>
        <p className="muted switch">
          {isLogin ? (
            <>No account yet? <Link to="/register">Create one</Link></>
          ) : (
            <>Already have an account? <Link to="/login">Log in</Link></>
          )}
        </p>
      </form>
    </div>
  );
}
