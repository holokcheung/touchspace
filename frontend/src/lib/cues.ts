/**
 * Short, distinct sounds (and a vibration where supported) that tell a listener when the
 * microphone opens and closes, so nobody has to look at the screen to know it's their turn.
 */

type Cue = "listen-start" | "listen-stop" | "error";

const PATTERNS: Record<Cue, { freqs: number[]; vibrate: number[] }> = {
  "listen-start": { freqs: [660, 880], vibrate: [40] }, // rising: your turn
  "listen-stop": { freqs: [880, 660], vibrate: [30, 60, 30] }, // falling: got it
  error: { freqs: [330, 330], vibrate: [120] },
};

let ctx: AudioContext | null = null;

export function playCue(cue: Cue): void {
  const { freqs, vibrate } = PATTERNS[cue];
  try {
    navigator.vibrate?.(vibrate);
  } catch {
    /* not supported */
  }
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    ctx ??= new AC();
    const t0 = ctx.currentTime;
    freqs.forEach((f, i) => {
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      const start = t0 + i * 0.11;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.18, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.1);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(start);
      osc.stop(start + 0.11);
    });
  } catch {
    /* audio unavailable */
  }
}
