// Microphone recorder for voice capture (docs/VOICE.md).
// getUserMedia → AudioWorklet (inline module) → downsample to 16 kHz mono → growing PCM16 buffer
// → WAV on demand. Nothing is stored; the buffer lives in memory until the page drops it.

export const TARGET_RATE = 16_000;
export const MAX_SECONDS = 300; // 5 minutes

export type RecorderErrorKind = "insecure" | "unsupported" | "denied" | "no_device" | "busy" | "unknown";

export class RecorderError extends Error {
  readonly kind: RecorderErrorKind;
  constructor(kind: RecorderErrorKind, message: string) {
    super(message);
    this.name = "RecorderError";
    this.kind = kind;
  }
}

/** The secure URL to suggest when the page isn't a secure context. */
export function secureAddress(): string {
  const port = window.location.port || "5173";
  return `https://${window.location.hostname}:${port}`;
}

/** Returns a reason voice can't work in this browser/page, or null if it can. */
export function voiceSupportProblem(): RecorderError | null {
  if (typeof window === "undefined") return new RecorderError("unsupported", "Voice isn't supported here.");
  if (!window.isSecureContext) {
    return new RecorderError("insecure", `Voice needs the secure address: ${secureAddress()}`);
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === "undefined") {
    return new RecorderError("unsupported", "This browser can't record audio. Try a recent Safari or Chrome.");
  }
  return null;
}

// The worklet just forwards mono input in ~2048-frame batches to the main thread.
const WORKLET_SOURCE = `
class RoloCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const input = inputs[0];
    if (input && input.length) {
      const ch0 = input[0];
      const chs = input.length;
      for (let i = 0; i < ch0.length; i++) {
        let s = 0;
        for (let c = 0; c < chs; c++) s += input[c][i];
        this.buf[this.n++] = s / chs;
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor("rolo-capture", RoloCapture);
`;

/** Streaming downsampler (box-filter average) from `inRate` to 16 kHz. */
class Downsampler {
  private ratio: number;
  private pos = 0; // fractional position into the virtual input stream for the next output sample
  private acc = 0;
  private accN = 0;

  constructor(inRate: number) {
    this.ratio = inRate / TARGET_RATE;
  }

  push(input: Float32Array): Int16Array {
    if (this.ratio === 1) return floatToPcm16(input);
    const out: number[] = [];
    for (let i = 0; i < input.length; i++) {
      this.acc += input[i];
      this.accN++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        out.push(this.acc / this.accN);
        this.acc = 0;
        this.accN = 0;
      }
    }
    return floatToPcm16(out);
  }
}

function floatToPcm16(input: ArrayLike<number>): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

/** Encodes 16 kHz mono PCM16 chunks as a WAV Blob. */
export function encodeWav(chunks: Int16Array[], totalSamples: number, rate = TARGET_RATE): Blob {
  const header = new ArrayBuffer(44);
  const v = new DataView(header);
  const dataBytes = totalSamples * 2;
  const str = (o: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i));
  };
  str(0, "RIFF");
  v.setUint32(4, 36 + dataBytes, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true); // fmt chunk size
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); // byte rate
  v.setUint16(32, 2, true); // block align
  v.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  v.setUint32(40, dataBytes, true);
  const parts: BlobPart[] = [header];
  for (const c of chunks) parts.push(c.buffer.slice(c.byteOffset, c.byteOffset + c.byteLength) as ArrayBuffer);
  return new Blob(parts, { type: "audio/wav" });
}

function mapGetUserMediaError(e: unknown): RecorderError {
  const name = (e as { name?: string })?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError")
    return new RecorderError("denied", "Allow microphone access for this site in your browser settings.");
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError")
    return new RecorderError("no_device", "No microphone was found. Connect one and try again.");
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError")
    return new RecorderError("busy", "The microphone is busy in another app. Close it and try again.");
  return new RecorderError("unknown", "Couldn't start the microphone. Try again.");
}

export interface RecorderOptions {
  /** Called when the 5-minute limit stops the recording automatically. */
  onAutoStop?: () => void;
  /** Called if the mic track ends unexpectedly (unplugged, permission revoked). */
  onTrackEnded?: () => void;
  maxSeconds?: number;
}

export class VoiceRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Int16Array[] = [];
  private samples = 0;
  private stopped = false;
  private opts: RecorderOptions;
  private maxSamples: number;

  constructor(opts: RecorderOptions = {}) {
    this.opts = opts;
    this.maxSamples = (opts.maxSeconds ?? MAX_SECONDS) * TARGET_RATE;
  }

  /** Seconds of audio captured so far. */
  get seconds(): number {
    return this.samples / TARGET_RATE;
  }

  get isRecording(): boolean {
    return !!this.ctx && !this.stopped;
  }

  async start(): Promise<void> {
    const problem = voiceSupportProblem();
    if (problem) throw problem;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      throw mapGetUserMediaError(e);
    }
    try {
      this.ctx = new AudioContext();
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "application/javascript" }));
      try {
        await this.ctx.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      if (this.ctx.state === "suspended") await this.ctx.resume();
      const down = new Downsampler(this.ctx.sampleRate);
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "rolo-capture", { numberOfInputs: 1, numberOfOutputs: 0 });
      this.node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        if (this.stopped) return;
        let pcm = down.push(ev.data);
        const room = this.maxSamples - this.samples;
        if (pcm.length > room) pcm = pcm.subarray(0, Math.max(0, room));
        if (pcm.length) {
          this.chunks.push(pcm);
          this.samples += pcm.length;
        }
        if (this.samples >= this.maxSamples) {
          void this.stop();
          this.opts.onAutoStop?.();
        }
      };
      this.source.connect(this.node);
      for (const t of this.stream.getAudioTracks()) {
        t.addEventListener("ended", () => {
          if (!this.stopped) this.opts.onTrackEnded?.();
        });
      }
    } catch (e) {
      await this.stop();
      if (e instanceof RecorderError) throw e;
      throw new RecorderError("unknown", "Couldn't start recording in this browser. Try again.");
    }
  }

  /** WAV of everything recorded so far (16 kHz mono PCM16). */
  wav(): Blob {
    return encodeWav(this.chunks, this.samples);
  }

  /** Stops the mic and audio graph. Recorded audio stays available via wav(). */
  async stop(): Promise<void> {
    this.stopped = true;
    try {
      this.source?.disconnect();
      this.node?.port.close();
      this.node?.disconnect();
    } catch {
      /* already disconnected */
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    const ctx = this.ctx;
    this.ctx = null;
    if (ctx && ctx.state !== "closed") await ctx.close().catch(() => {});
  }

  /** Stops and forgets all audio. */
  async discard(): Promise<void> {
    await this.stop();
    this.chunks = [];
    this.samples = 0;
  }
}

/**
 * Live transcription loop: every `intervalMs`, if no request is in flight, POSTs the whole
 * recording so far. Responses are applied only if newer than the last applied one.
 */
export class LiveTranscriber {
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight = false;
  private seq = 0;
  private appliedSeq = 0;
  private lastSentSamples = -1;
  private ctrl = new AbortController();

  constructor(
    private rec: VoiceRecorder,
    private transcribe: (wav: Blob, signal: AbortSignal) => Promise<{ text: string }>,
    private onText: (text: string) => void,
    private onError: (e: unknown) => void,
    private intervalMs = 1500,
  ) {}

  start() {
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
  }

  private async tick() {
    if (this.inFlight) return;
    const samples = Math.round(this.rec.seconds * TARGET_RATE);
    if (samples < TARGET_RATE / 2 || samples === this.lastSentSamples) return; // < 0.5 s or nothing new
    this.inFlight = true;
    this.lastSentSamples = samples;
    const mySeq = ++this.seq;
    try {
      const r = await this.transcribe(this.rec.wav(), this.ctrl.signal);
      if (mySeq > this.appliedSeq && !this.ctrl.signal.aborted) {
        this.appliedSeq = mySeq;
        this.onText(r.text);
      }
    } catch (e) {
      if (!this.ctrl.signal.aborted) this.onError(e);
    } finally {
      this.inFlight = false;
    }
  }

  /** Stops the loop and cancels any request in flight (its result is ignored). */
  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.ctrl.abort();
  }
}
