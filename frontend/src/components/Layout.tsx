import { useEffect, useRef, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
export default function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [pathname]);
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <main id="main" ref={mainRef} tabIndex={-1} className="outline-none">
        {children}
      </main>
    </>
  );
}
