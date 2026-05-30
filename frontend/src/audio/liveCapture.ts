import { resampleLinear, floatTo16BitPCM } from "./wav";

export type AudioPush = (base64Pcm: string) => void;

// ---- AudioWorklet Processor (inline as a Blob URL) ----
const WORKLET_CODE = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
  }
  process(inputs) {
    const ch = inputs[0]?.[0];
    if (ch && ch.length > 0) {
      // Copy the Float32 samples to avoid detached ArrayBuffer issues
      const copy = new Float32Array(ch.length);
      copy.set(ch);
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-capture-processor', PcmCaptureProcessor);
`;

/**
 * Captures mic audio, resamples to 16kHz, and emits raw PCM base64 chunks
 * every ~100ms for ultra-low latency with the Gemini Live API.
 *
 * Uses AudioWorkletNode (off-main-thread) for smooth, glitch-free capture.
 * Falls back to ScriptProcessorNode only if AudioWorklet is unavailable.
 */
export class LiveMicCapture {
  private ctx: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private proc: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private stream: MediaStream | null = null;
  private buf: Float32Array[] = [];
  private interval: number | null = null;
  private useWorklet = false;

  constructor(
    private readonly onChunk: AudioPush,
    private readonly chunkMs = 100 // 10 chunks/sec for low latency
  ) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
      video: false,
    });
    const Ctor = window.AudioContext || (window as any).webkitAudioContext;
    this.ctx = new Ctor();
    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }
    const rate = this.ctx.sampleRate;
    this.source = this.ctx.createMediaStreamSource(this.stream);

    // Try AudioWorklet first (modern, off-main-thread, lower latency)
    if (this.ctx.audioWorklet) {
      try {
        const blob = new Blob([WORKLET_CODE], { type: "application/javascript" });
        const url = URL.createObjectURL(blob);
        await this.ctx.audioWorklet.addModule(url);
        URL.revokeObjectURL(url);

        this.workletNode = new AudioWorkletNode(this.ctx, "pcm-capture-processor");
        this.workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
          this.buf.push(e.data);
        };
        this.source.connect(this.workletNode);
        // AudioWorkletNode needs a destination connection to keep processing
        const mute = this.ctx.createGain();
        mute.gain.value = 0;
        this.workletNode.connect(mute);
        mute.connect(this.ctx.destination);
        this.useWorklet = true;
      } catch {
        // Fallback to ScriptProcessor if Worklet fails
        this.useWorklet = false;
      }
    }

    // Fallback: ScriptProcessorNode (deprecated but universally supported)
    if (!this.useWorklet) {
      const bufferSize = 2048; // Smaller buffer = lower latency
      this.proc = this.ctx.createScriptProcessor(bufferSize, 1, 1);
      this.proc.onaudioprocess = (e) => {
        const ch = e.inputBuffer.getChannelData(0);
        const copy = new Float32Array(ch.length);
        copy.set(ch);
        this.buf.push(copy);
      };
      const mute = this.ctx.createGain();
      mute.gain.value = 0;
      this.source.connect(this.proc);
      this.proc.connect(mute);
      mute.connect(this.ctx.destination);
    }

    // Flush accumulated audio chunks at the configured interval
    this.interval = window.setInterval(() => {
      void this._flush(rate);
    }, this.chunkMs);
  }

  private async _flush(inputRate: number): Promise<void> {
    if (!this.buf.length) return;
    let total = 0;
    for (const b of this.buf) total += b.length;
    const merged = new Float32Array(total);
    let o = 0;
    for (const b of this.buf) {
      merged.set(b, o);
      o += b.length;
    }
    this.buf = [];
    
    // Resample to 16kHz as required by Gemini
    const targetRate = 16000;
    const resampled = resampleLinear(merged, inputRate, targetRate);
    const pcm = floatTo16BitPCM(resampled);
    
    // Convert directly to base64 (no WAV header)
    const b64 = await new Promise<string>((resolve, reject) => {
      try {
        const bytes = new Uint8Array(pcm.buffer);
        let binary = "";
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
          binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
        }
        resolve(btoa(binary));
      } catch (e) {
        reject(e);
      }
    });
    this.onChunk(b64);
  }

  async stop(): Promise<void> {
    if (this.interval) window.clearInterval(this.interval);
    this.interval = null;
    try {
      if (this.ctx) await this._flush(this.ctx.sampleRate);
    } catch {
      /* noop */
    }
    this.workletNode?.disconnect();
    this.proc?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    this.workletNode = null;
    this.proc = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
    this.buf = [];
  }
}
