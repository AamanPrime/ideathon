import { encodeWavPcm16, floatTo16BitPCM, resampleLinear } from "./wav";

export type AudioPush = (base64Wav: string) => void;

/**
 * Captures mic via AudioContext, resamples to 16 kHz mono, emits WAV base64 chunks on an interval.
 * Uses ScriptProcessorNode for broad browser support in hackathon demos.
 */
export class MicCapture {
  private ctx: AudioContext | null = null;
  private proc: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private stream: MediaStream | null = null;
  private buf: Float32Array[] = [];
  private interval: number | null = null;

  constructor(
    private readonly onChunk: AudioPush,
    private readonly chunkMs = 2400
  ) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        channelCount: 1,
      },
      video: false,
    });
    this.ctx = new AudioContext();
    const rate = this.ctx.sampleRate;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    const bufferSize = 4096;
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
    const targetRate = 16000;
    const resampled = resampleLinear(merged, inputRate, targetRate);
    const pcm = floatTo16BitPCM(resampled);
    const wav = encodeWavPcm16(pcm, targetRate);
    const b64 = await new Promise<string>((resolve, reject) => {
      try {
        const bytes = new Uint8Array(wav);
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
    this.proc?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    this.proc = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
    this.buf = [];
  }
}
