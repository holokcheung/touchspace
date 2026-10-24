/**
 * The walk-through's sound: soft pink noise in each ear, muffled on the side of a nearby
 * surface, ticks for something ahead, and distinct cues for bumps, doorways and "no map data".
 * Every number comes from shared/soundscape.json via SOUNDSCAPE.
 */
import { SOUNDSCAPE, muffleFor, pulseRateFor, type CueName, type SoundscapeSettings } from "./soundscape";

export interface EarInput {
  left: number | null;
  ahead: number | null;
  right: number | null;
  /** False outside the map (or, on the phone, when sensing is lost). */
  hasData: boolean;
}

type AudioContextCtor = typeof AudioContext;

function audioContextCtor(): AudioContextCtor | undefined {
  if (typeof window === "undefined") return undefined;
  return window.AudioContext ?? (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
}

/** A few seconds of pink noise (Paul Kellet's filter), looped. Each ear gets its own buffer. */
function pinkNoise(ctx: AudioContext, seconds = 4): AudioBuffer {
  const buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * seconds), ctx.sampleRate);
  const data = buf.getChannelData(0);
  let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
  for (let i = 0; i < data.length; i++) {
    const white = Math.random() * 2 - 1;
    b0 = 0.99886 * b0 + white * 0.0555179;
    b1 = 0.99332 * b1 + white * 0.0750759;
    b2 = 0.969 * b2 + white * 0.153852;
    b3 = 0.8665 * b3 + white * 0.3104856;
    b4 = 0.55 * b4 + white * 0.5329522;
    b5 = -0.7616 * b5 - white * 0.016898;
    data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362) * 0.11;
    b6 = white * 0.115926;
  }
  return buf;
}

export class SoundscapeAudio {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private bed: GainNode | null = null;
  private ears: { filter: BiquadFilterNode; gain: GainNode }[] = [];
  private sources: AudioBufferSourceNode[] = [];
  private scheduler: number | null = null;
  private noDataTimer: number | null = null;
  private pulseHz: number | null = null;
  private nextTick = 0;
  private hasData = true;

  constructor(private readonly s: SoundscapeSettings = SOUNDSCAPE) {}

  static supported(): boolean {
    return Boolean(audioContextCtor());
  }

  get running(): boolean {
    return this.ctx !== null;
  }

  /** Must be called from a click or key press: browsers only allow audio after a gesture. */
  async start(volume = this.s.noise.default_volume): Promise<void> {
    if (this.ctx) return;
    const AC = audioContextCtor();
    if (!AC) throw new Error("This browser can't play generated sound.");
    // iPhone Safari: play even when the ring/silent switch is on silent.
    const session = (navigator as unknown as { audioSession?: { type: string } }).audioSession;
    if (session) session.type = "playback";
    const ctx = new AC();
    this.ctx = ctx;
    await ctx.resume();

    this.master = ctx.createGain();
    this.master.gain.value = volume;
    this.master.connect(ctx.destination);
    this.bed = ctx.createGain();
    this.bed.connect(this.master);
    const merger = ctx.createChannelMerger(2);
    merger.connect(this.bed);

    this.ears = [0, 1].map((channel) => {
      const src = ctx.createBufferSource();
      src.buffer = pinkNoise(ctx);
      src.loop = true;
      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = this.s.muffle.open_cutoff_hz;
      filter.Q.value = this.s.muffle.filter_q;
      const gain = ctx.createGain();
      gain.gain.value = this.s.noise.level;
      src.connect(filter).connect(gain).connect(merger, 0, channel);
      src.start();
      this.sources.push(src);
      return { filter, gain };
    });

    this.scheduler = window.setInterval(() => this.scheduleTicks(), 25);
  }

  setVolume(volume: number): void {
    if (this.ctx && this.master) this.master.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.05);
  }

  update(input: EarInput): void {
    const ctx = this.ctx;
    if (!ctx || !this.bed) return;
    const now = ctx.currentTime;
    const tc = this.s.noise.smoothing_s;
    [input.left, input.right].forEach((distance, i) => {
      const m = muffleFor(distance, this.s);
      this.ears[i].filter.frequency.setTargetAtTime(m.cutoffHz, now, tc);
      this.ears[i].gain.gain.setTargetAtTime(this.s.noise.level * m.gain, now, tc);
    });

    const rate = input.hasData ? pulseRateFor(input.ahead, this.s) : null;
    if (rate !== null && this.pulseHz === null) this.nextTick = now + 0.02;
    this.pulseHz = rate;

    if (input.hasData !== this.hasData) {
      this.hasData = input.hasData;
      // With no information the noise fades out and a repeating cue takes over, so quiet
      // never sounds like open space.
      this.bed.gain.setTargetAtTime(input.hasData ? 1 : 0, now, 0.15);
      if (input.hasData) this.clearNoData();
      else {
        this.cue("no_data");
        this.noDataTimer = window.setInterval(() => this.cue("no_data"), (this.s.cues.no_data.repeat_s ?? 2) * 1000);
      }
    }
  }

  cue(name: CueName): void {
    const c = this.s.cues[name];
    try {
      if (c.vibrate_ms.length) navigator.vibrate?.(c.vibrate_ms);
    } catch {
      /* not supported (iPhone Safari) */
    }
    const ctx = this.ctx;
    if (!ctx || !this.master) return;
    const t0 = ctx.currentTime + 0.01;
    c.freqs_hz.forEach((f, i) => this.beep(f, t0 + i * (c.duration_s + 0.02), c.duration_s, this.s.cues.level));
  }

  async stop(): Promise<void> {
    if (this.scheduler !== null) window.clearInterval(this.scheduler);
    this.scheduler = null;
    this.clearNoData();
    this.sources.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    this.sources = [];
    this.ears = [];
    const ctx = this.ctx;
    this.ctx = null;
    this.master = null;
    this.bed = null;
    this.pulseHz = null;
    this.hasData = true;
    await ctx?.close();
  }

  private clearNoData() {
    if (this.noDataTimer !== null) window.clearInterval(this.noDataTimer);
    this.noDataTimer = null;
  }

  private scheduleTicks() {
    const ctx = this.ctx;
    if (!ctx) return;
    const p = this.s.ahead_pulse;
    while (this.pulseHz !== null && this.nextTick < ctx.currentTime + 0.1) {
      if (this.nextTick >= ctx.currentTime) this.beep(p.tick_hz, this.nextTick, p.tick_s, p.level);
      this.nextTick += 1 / this.pulseHz;
    }
  }

  private beep(freq: number, at: number, duration: number, level: number) {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(level, at + Math.min(0.01, duration / 4));
    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration);
    // A mono source into the stereo master plays in both ears.
    osc.connect(gain).connect(this.master!);
    osc.start(at);
    osc.stop(at + duration + 0.02);
  }
}
