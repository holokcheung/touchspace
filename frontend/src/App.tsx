import { lazy, Suspense, useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import Editor from "./pages/Editor";
import Landing from "./pages/Landing";
import NotFound from "./pages/NotFound";
import Upload from "./pages/Upload";
import VoiceExplorer from "./pages/VoiceExplorer";
import Walkthrough from "./pages/Walkthrough";

// three.js is large; only load it when someone opens the 3D preview.
const Preview = lazy(() => import("./pages/Preview"));

const TITLES: [RegExp, string][] = [
  [/^\/$/, "TouchSpace AI"],
  [/^\/upload/, "Upload a scan · TouchSpace AI"],
  [/\/edit$/, "Floor plan editor · TouchSpace AI"],
  [/\/preview$/, "3D tactile map · TouchSpace AI"],
  [/\/voice$/, "Voice explorer · TouchSpace AI"],
  [/\/walk$/, "Walk-through · TouchSpace AI"],
];

function useDocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = TITLES.find(([re]) => re.test(pathname))?.[1] ?? "TouchSpace AI";
  }, [pathname]);
}

export default function App() {
  useDocumentTitle();
  return (
    <Layout>
      <Suspense fallback={<p className="p-8 text-muted" role="status">Loading…</p>}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/maps/:mapId/edit" element={<Editor />} />
          <Route path="/maps/:mapId/preview" element={<Preview />} />
          <Route path="/maps/:mapId/voice" element={<VoiceExplorer />} />
          <Route path="/maps/:mapId/walk" element={<Walkthrough />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
