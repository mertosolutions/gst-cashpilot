"use client";
import { API_BASE } from "./api";

/* Gemini Live voice session. Microphone -> 16 kHz PCM16 -> WebSocket -> API -> Gemini Live; reply audio (24 kHz PCM16) comes back
   the same way and is played as it arrives. Everything else (transcripts, result rows) arrives as JSON messages. */

export type LiveMessage =
  | { type: "ready"; model: string; month: string }
  | { type: "status"; text: string }
  | { type: "user_transcript" | "assistant_transcript"; text: string }
  | { type: "results"; question: string; data: unknown }
  | { type: "interrupted" | "turn_complete" }
  | { type: "error"; message: string };

export type LiveState = "idle" | "connecting" | "listening" | "speaking";

const WORKLET = `
class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.pos = 0; this.last = 0; this.out = []; this.step = sampleRate / 16000; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const cur = ch[i];
      while (this.pos < 1) {
        this.out.push(this.last + (cur - this.last) * this.pos);
        this.pos += this.step;
      }
      this.pos -= 1; this.last = cur;
    }
    if (this.out.length >= 1280) {
      const pcm = new Int16Array(this.out.length);
      for (let i = 0; i < this.out.length; i++) { const v = Math.max(-1, Math.min(1, this.out[i])); pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff; }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
      this.out = [];
    }
    return true;
  }
}
registerProcessor("capture", Capture);
`;

export function liveSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && "AudioWorklet" in window && "WebSocket" in window;
}

export class LiveVoice {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private speakingTimer: ReturnType<typeof setTimeout> | null = null;
  state: LiveState = "idle";

  constructor(private onMessage: (m: LiveMessage) => void, private onState: (s: LiveState) => void) {}

  private set(s: LiveState) { if (this.state !== s) { this.state = s; this.onState(s); } }

  private within<T>(p: Promise<T>, ms: number, msg: string): Promise<T> {
    return new Promise<T>((res, rej) => { const t = setTimeout(() => rej(new Error(msg)), ms); p.then((v) => { clearTimeout(t); res(v); }, (e) => { clearTimeout(t); rej(e); }); });
  }

  async start(opts: { month: string | null; authQuery: Record<string, string> }) {
    this.set("connecting");
    try {
      // If the browser already blocked the microphone for this site it will not ask again, so say what to do instead of waiting.
      const perm = await navigator.permissions?.query({ name: "microphone" as PermissionName }).catch(() => null);
      if (perm?.state === "denied") throw new Error("denied");
    } catch (e) {
      if ((e as Error).message === "denied") {
        this.set("idle");
        throw new Error("The microphone is blocked for this site. Click the lock icon next to the address bar, set Microphone to Allow, then reload and tap the mic again.");
      }
    }
    try {
      this.stream = await this.within(navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }), 6000, "timeout");
    } catch (e) {
      this.set("idle");
      throw new Error((e as Error).message === "timeout"
        ? "The browser did not give microphone access. Click the lock icon next to the address bar, allow the microphone, and check System Settings > Privacy > Microphone for your browser."
        : "Microphone access was blocked. Allow the microphone for this site in your browser settings.");
    }
    this.ctx = new AudioContext();
    try { await this.within(this.ctx.resume(), 5000, "audio"); }
    catch { this.stream.getTracks().forEach((t) => t.stop()); this.set("idle"); throw new Error("The browser could not start audio. Click once on the page and try the mic again."); }
    // "localhost" can resolve to IPv6 first while the API listens on IPv4 only, so use the IPv4 address for the socket
    const url = new URL(API_BASE.replace(/^http/, "ws").replace("//localhost", "//127.0.0.1") + "/live");
    if (opts.month) url.searchParams.set("month", opts.month);
    const ws = new WebSocket(url.toString());
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    let stage = "the browser could not open a connection to the API (" + url.host + ")";
    const slow = setTimeout(() => { this.onMessage({ type: "error", message: `Gemini Live is taking too long. Stuck at: ${stage}.` }); this.stop(true); }, 30000);
    ws.onopen = () => {
      stage = "the API accepted the connection but has not finished the sign-in check";
      ws.send(JSON.stringify({ type: "auth", ...opts.authQuery }));
    };
    ws.onmessage = (e) => {
      if (typeof e.data === "string") {
        const m = JSON.parse(e.data) as LiveMessage;
        if (m.type === "status") { stage = m.text; this.onMessage(m); return; }
        if (m.type === "ready" || m.type === "error") clearTimeout(slow);
        if (m.type === "ready") this.beginCapture();
        if (m.type === "interrupted") this.stopPlayback();
        this.onMessage(m);
      } else this.play(e.data as ArrayBuffer);
    };
    ws.onclose = () => { clearTimeout(slow); if (this.ws === ws) this.stop(false); };
    ws.onerror = () => {
      clearTimeout(slow);
      if (this.ws !== ws) return;
      this.onMessage({ type: "error", message: `The browser could not open the voice connection to ${url.host}. Check the browser console for a WebSocket error and make sure the API is reachable from this device.` });
      this.stop(true);
    };
  }

  private async beginCapture() {
    if (!this.ctx || !this.stream) return;
    const blob = new Blob([WORKLET], { type: "application/javascript" });
    await this.ctx.audioWorklet.addModule(URL.createObjectURL(blob));
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "capture");
    this.node.port.onmessage = (e) => { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data as ArrayBuffer); };
    src.connect(this.node);
    this.set("listening");
  }

  private play(buf: ArrayBuffer) {
    if (!this.ctx) return;
    const pcm = new Int16Array(buf);
    const f = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 0x8000;
    const ab = this.ctx.createBuffer(1, f.length, 24000);
    ab.copyToChannel(f, 0);
    const s = this.ctx.createBufferSource();
    s.buffer = ab; s.connect(this.ctx.destination);
    const at = Math.max(this.ctx.currentTime + 0.02, this.nextTime);
    s.start(at); this.nextTime = at + ab.duration;
    this.sources.add(s); s.onended = () => this.sources.delete(s);
    this.set("speaking");
    if (this.speakingTimer) clearTimeout(this.speakingTimer);
    this.speakingTimer = setTimeout(() => { if (this.state === "speaking") this.set("listening"); }, Math.max(0, (this.nextTime - this.ctx.currentTime) * 1000) + 150);
  }

  private stopPlayback() {
    this.sources.forEach((s) => { try { s.stop(); } catch { /* already ended */ } });
    this.sources.clear(); this.nextTime = 0;
    if (this.state === "speaking") this.set("listening");
  }

  sendText(text: string) { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "text", text })); }

  stop(closeSocket = true) {
    this.stopPlayback();
    try { this.node?.disconnect(); } catch { /* ignore */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    try { this.ctx?.close(); } catch { /* ignore */ }
    if (closeSocket && this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
    this.ws = null; this.ctx = null; this.stream = null; this.node = null;
    this.set("idle");
  }
}
