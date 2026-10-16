import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, type User } from "./api";
import LoginPage from "./pages/LoginPage";
import RunsPage from "./pages/RunsPage";
import RunPage from "./pages/RunPage";
import TemplatePage from "./pages/TemplatePage";
import TemplatesPage from "./pages/TemplatesPage";

type Auth = { user: User | null; setUser: (user: User | null) => void };
const AuthContext = createContext<Auth>({ user: null, setUser: () => {} });
export const useAuth = () => useContext(AuthContext);

export default function App() {
  // undefined while the session is being checked, null when logged out.
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setUser, () => setUser(null));
  }, []);

  if (user === undefined) return <div className="page-loading" aria-busy="true" />;

  return (
    <AuthContext.Provider value={{ user, setUser }}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage mode="login" />} />
        <Route path="/register" element={user ? <Navigate to="/" replace /> : <LoginPage mode="register" />} />
        <Route path="/" element={<RequireUser><Shell><RunsPage /></Shell></RequireUser>} />
        <Route path="/runs/:id" element={<RequireUser><Shell><RunPage /></Shell></RequireUser>} />
        <Route path="/templates" element={<RequireUser><Shell><TemplatesPage /></Shell></RequireUser>} />
        <Route path="/templates/:id" element={<RequireUser><Shell><TemplatePage /></Shell></RequireUser>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthContext.Provider>
  );
}

function RequireUser({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  return user ? children : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

function Shell({ children }: { children: ReactNode }) {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();

  async function logout() {
    await api.logout().catch(() => {});
    setUser(null);
    navigate("/login");
  }

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          <img src="/favicon.svg" alt="" width={24} height={24} />
          <span className="brand-name">Document Generator</span>
        </Link>
        <nav className="topnav">
          <NavLink to="/" end>Documents</NavLink>
          <NavLink to="/templates">Templates</NavLink>
        </nav>
        <div className="topbar-user">
          <span className="muted email">{user?.email}</span>
          <button className="button ghost small" onClick={logout}>Log out</button>
        </div>
      </header>
      <main className="container">{children}</main>
    </>
  );
}
