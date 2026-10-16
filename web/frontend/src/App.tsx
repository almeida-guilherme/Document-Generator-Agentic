import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type User } from "./api";
import { Logo, initials } from "./components";
import AccountPage from "./pages/AccountPage";
import LandingPage from "./pages/LandingPage";
import LoginPage from "./pages/LoginPage";
import NewProjectPage from "./pages/NewProjectPage";
import ProjectsPage from "./pages/ProjectsPage";
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

  const app = (page: ReactNode) => <RequireUser><Shell>{page}</Shell></RequireUser>;
  return (
    <AuthContext.Provider value={{ user, setUser }}>
      <Routes>
        {/* Logged out, "/" is the landing page; logged in, it is the list of projects. */}
        <Route path="/" element={user ? app(<ProjectsPage />) : <LandingPage />} />
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/register" element={<Navigate to="/login?mode=register" replace />} />
        <Route path="/projects/new" element={app(<NewProjectPage />)} />
        <Route path="/runs/:id" element={app(<RunPage />)} />
        <Route path="/templates" element={app(<TemplatesPage />)} />
        <Route path="/templates/:id" element={app(<TemplatePage />)} />
        <Route path="/account" element={app(<AccountPage />)} />
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
  const { user } = useAuth();
  const { pathname } = useLocation();
  const inProjects = pathname === "/" || pathname.startsWith("/projects") || pathname.startsWith("/runs");
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <Logo to="/" label="Pidi projects" />
          <nav aria-label="App" className="app-nav">
            <NavLink to="/" className={inProjects ? "active" : undefined} aria-current={inProjects ? "page" : undefined}>
              Projects
            </NavLink>
            <NavLink to="/templates">Templates</NavLink>
            <NavLink to="/account">Account</NavLink>
            {user && <NavLink to="/account" className="avatar" aria-label="Your account">{initials(user)}</NavLink>}
          </nav>
        </div>
      </header>
      {children}
    </>
  );
}
