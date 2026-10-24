import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("touchspace-theme", dark ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }, [dark]);
  return (
    <button
      type="button"
      className="btn-secondary min-h-10 px-3 text-sm"
      aria-pressed={dark}
      onClick={() => setDark((d) => !d)}
    >
      {dark ? "Dark mode on" : "Dark mode off"}
    </button>
  );
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 font-semibold ${isActive ? "bg-accent-soft text-text underline underline-offset-4" : "text-muted hover:text-text"}`;

export default function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  // Move focus to the page content on navigation so screen reader users hear the new page.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-text"
      >
        Skip to main content
      </a>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            TouchSpace AI
          </Link>
          <nav aria-label="Main" className="flex flex-wrap items-center gap-1">
            <NavLink to="/" end className={navClass}>
              Home
            </NavLink>
            <NavLink to="/upload" className={navClass}>
              Upload scan
            </NavLink>
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main id="main" ref={mainRef} tabIndex={-1} className="flex-1 outline-none">
        {children}
      </main>
      <footer className="border-t border-line px-4 py-6 text-center text-sm text-muted">
        TouchSpace AI is a Cal Hacks 13.0 prototype. Tactile dimensions are starting points for print testing,
        not a validated standard.
      </footer>
    </div>
  );
}
