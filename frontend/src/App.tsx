import { lazy, Suspense, useEffect } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";
const Walkthrough = lazy(() => import("./pages/Walkthrough"));
function LegacyMapRedirect() {
  const { mapId } = useParams();
  return (
    <Navigate to={`/maps/${encodeURIComponent(mapId ?? "")}/walk`} replace />
  );
}
export default function App() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = `${pathname.includes("/maps/") ? "Walkthrough" : "Your spaces"} · TouchSpace`;
  }, [pathname]);
  return (
    <Layout>
      <Suspense
        fallback={
          <p className="p-8 text-muted" role="status">
            Opening your space…
          </p>
        }
      >
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/upload" element={<Navigate to="/" replace />} />
          <Route path="/maps/:mapId/walk" element={<Walkthrough />} />
          {["edit", "preview", "voice"].map((page) => (
            <Route
              key={page}
              path={`/maps/:mapId/${page}`}
              element={<LegacyMapRedirect />}
            />
          ))}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
