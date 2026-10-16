import { createContext, useContext, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
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
            {user && <AccountMenu user={user} />}
          </nav>
        </div>
      </header>
      {children}
    </>
  );
}

export function useLogout() {
  const { setUser } = useAuth();
  const navigate = useNavigate();
  return async () => {
    await api.logout().catch(() => {});
    setUser(null);
    navigate("/");
  };
}

/**
 * The avatar; hovering it (or focusing it with the keyboard) opens a menu with the account and Log out.
 * Touch screens have no hover, so there a tap opens the menu instead of going to the account page.
 */
function AccountMenu({ user }: { user: User }) {
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    // Leaving the page closes the menu, also when it is open because a link in it has focus.
    setOpen(false);
    if (ref.current?.contains(document.activeElement)) (document.activeElement as HTMLElement).blur();
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => ref.current?.contains(e.target as Node) || setOpen(false);
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  function tap(e: MouseEvent) {
    if (window.matchMedia("(hover: none)").matches) {
      e.preventDefault();
      setOpen(!open);
    }
  }

  return (
    <div className={open ? "account-menu open" : "account-menu"} ref={ref}>
      <NavLink to="/account" className="avatar" aria-label="Your account" aria-haspopup="menu" aria-expanded={open}
               onClick={tap}>
        {initials(user)}
      </NavLink>
      <div className="account-pop">
        <div className="account-panel" role="menu">
          <div className="account-who">
            {user.name && <strong>{user.name}</strong>}
            <span>{user.email}</span>
          </div>
          <NavLink to="/account" role="menuitem">Account</NavLink>
          <button type="button" role="menuitem" onClick={logout}>Log out</button>
        </div>
      </div>
    </div>
  );
}
