export type IconName =
  | "map"
  | "audio"
  | "dotpad"
  | "help"
  | "mic"
  | "close"
  | "arrow"
  | "back"
  | "expand"
  | "send";
const paths: Record<IconName, string> = {
  map: "M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2V5zm6-2v16m6-14v16",
  audio: "M4 14v-3a8 8 0 0116 0v3M4 12H2v7h4v-7H4zm16 0h2v7h-4v-7h2z",
  dotpad: "M4 4h1m6 0h1m6 0h1M4 11h1m6 0h1m6 0h1M4 18h1m6 0h1m6 0h1",
  help: "M9 8a3 3 0 016 0c0 2-3 2-3 5m0 4h.01M22 12a10 10 0 11-20 0 10 10 0 0120 0z",
  mic: "M9 5a3 3 0 016 0v7a3 3 0 01-6 0V5zm-3 6v1a6 6 0 0012 0v-1m-6 7v4m-4 0h8",
  close: "M6 6l12 12M6 18L18 6",
  arrow: "M6 14l6-6 6 6",
  back: "M15 5l-7 7 7 7",
  expand: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5",
  send: "M3 3l18 9-18 9 4-9-4-9zm4 9h14",
};
export default function Icon({
  name,
  className = "",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      className={className}
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={name === "dotpad" ? 3.5 : 1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
