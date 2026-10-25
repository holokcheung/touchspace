import { useEffect, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { MapResponse, MapSummary } from "../api/types";
import Icon from "../components/Icon";

export default function Landing() {
  const navigate = useNavigate();
  const [maps, setMaps] = useState<MapSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    let alive = true;
    api
      .listMaps()
      .then((data) => {
        if (alive) setMaps(data);
      })
      .catch(() => {})
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);
  async function open(label: string, action: () => Promise<MapResponse>) {
    if (busy) return;
    setBusy(label);
    setError("");
    try {
      const { map } = await action();
      navigate(`/maps/${encodeURIComponent(map.id)}/walk`);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? [e.message, ...e.details].join(" ")
          : e instanceof Error
            ? e.message
            : String(e),
      );
      setBusy("");
    }
  }
  function upload(file: File) {
    if (
      !file.name.toLowerCase().endsWith(".json") &&
      file.type !== "application/json"
    ) {
      setError(
        `"${file.name}" is not a JSON file. Choose a RoomPlan or TouchSpace JSON map.`,
      );
      return;
    }
    void open("Opening your scan…", () => api.uploadScan(file));
  }
  function drop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && !busy) upload(file);
  }
  return (
    <div
      className="spaces-page"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node))
          setDragging(false);
      }}
      onDrop={drop}
    >
      <header className="spaces-header">
        <Link to="/" className="wordmark">
          <img src="/favicon.svg" alt="" />
          TouchSpace<span>EXPLORE WITH CONFIDENCE</span>
        </Link>
        <span className="web-edition">WEB WALKTHROUGH</span>
      </header>
      <div className="spaces-content">
        <div className="spaces-intro">
          <span className="eyebrow">A LITTLE FAMILIARITY GOES A LONG WAY</span>
          <h1>
            Know the space.
            <br />
            <em>Before you get there.</em>
          </h1>
          <p>
            Step inside a map. Find your way with spatial sound,
            <br className="hidden sm:block" /> a first-person view, and a guide
            you can talk to.
          </p>
        </div>
        <section className="featured-space" aria-labelledby="demo-title">
          <div className="space-illustration" aria-hidden="true">
            <div className="illustration-grid" />
            <div className="mini-room room-one" />
            <div className="mini-room room-two" />
            <div className="mini-room room-three" />
            <div className="mini-room room-four" />
            <div className="mini-door" />
            <div className="mini-walker" />
            <span className="illustration-label">
              YOUR NEXT STEP, MADE FAMILIAR.
            </span>
          </div>
          <div className="featured-content">
            <span className="eyebrow">START EXPLORING</span>
            <h2 id="demo-title">A space to practice.</h2>
            <p>
              Walk through our demo building. Explore the rooms, listen for
              doorways, and ask your guide where to go.
            </p>
            <button
              className="btn-primary"
              disabled={Boolean(busy)}
              onClick={() => void open("Opening demo…", api.createDemo)}
            >
              Try Demo <span aria-hidden="true">↗</span>
            </button>
            <span className="demo-note">
              Synthetic layout · no account or API key needed
            </span>
          </div>
        </section>
        <section className="your-spaces" aria-labelledby="spaces-title">
          <div className="spaces-section-heading">
            <div>
              <span className="eyebrow">PICK UP WHERE YOU LEFT OFF</span>
              <h2 id="spaces-title">Your spaces</h2>
            </div>
            <label
              className={`btn-secondary cursor-pointer ${busy ? "opacity-50" : ""}`}
            >
              <span aria-hidden="true">＋</span> Import a scan
              <input
                aria-label="Choose a file"
                type="file"
                accept=".json,application/json"
                className="sr-only"
                disabled={Boolean(busy)}
                onChange={(e) => {
                  if (e.target.files?.[0]) upload(e.target.files[0]);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
          {loading ? (
            <p className="text-sm text-muted">Loading saved spaces…</p>
          ) : maps.length ? (
            <ul className="space-list">
              {maps.map((m) => (
                <li key={m.id}>
                  <Link to={`/maps/${encodeURIComponent(m.id)}/walk`}>
                    <span className="space-card-icon">
                      <Icon name="map" />
                    </span>
                    <span>
                      <strong>{m.name}</strong>
                      <small>
                        {m.synthetic ? "Demo layout" : "Imported map"} ·{" "}
                        {m.landmarks} places
                      </small>
                    </span>
                    <span aria-hidden="true">↗</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="spaces-empty">
              <Icon name="map" />
              <p>
                Your saved spaces will appear here.
                <br />
                <span>
                  Import a RoomPlan or TouchSpace JSON map to walk through it.
                </span>
              </p>
            </div>
          )}
          <button
            className="sample-link"
            disabled={Boolean(busy)}
            aria-describedby="sample-note"
            onClick={() =>
              void open("Opening apartment…", api.createRoomPlanSample)
            }
          >
            Or explore the public RoomPlan sample{" "}
            <span aria-hidden="true">↗</span>
          </button>
          <p id="sample-note" className="sample-note">
            Apartment scan from an open-source project, not a scan by our team.
            Room labels are unconfirmed.
          </p>
        </section>
        {busy && (
          <p role="status" className="library-status">
            {busy}
          </p>
        )}
        {error && (
          <p role="alert" className="library-error">
            {error}
          </p>
        )}
        <footer className="spaces-footer">
          <span>
            <Icon name="audio" /> Best explored with headphones
          </span>
          <span>Virtual practice from recorded maps</span>
        </footer>
      </div>
      {dragging && (
        <div className="drop-overlay">
          Drop your JSON map to enter the space
        </div>
      )}
    </div>
  );
}
