/**
 * Plays raw PCM streaming audio directly from base64 chunks without needing WAV headers.
 * Specifically handles the 24kHz PCM output from the Gemini Live API.
 */
export class LiveAudioPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;
  private activeSources: AudioBufferSourceNode[] = [];

  get isPlaying(): boolean {
    return this.activeSources.length > 0;
  }

  init() {
    if (!this.ctx) {
      const Ctor = window.AudioContext || (window as any).webkitAudioContext;
      this.ctx = new Ctor({ sampleRate: 24000 }); // Gemini outputs 24kHz
      this.nextStartTime = this.ctx.currentTime;
      this.activeSources = [];
    }
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume().catch(e => console.error("Failed to resume AudioContext:", e));
    }
  }

  playChunk(base64Pcm: string) {
    if (!this.ctx) this.init();
    if (this.ctx && this.ctx.state === "suspended") {
      this.ctx.resume().catch(e => console.error("Failed to resume AudioContext in playChunk:", e));
    }
    
    // Decode base64 to Int16 array
    const binary = atob(base64Pcm);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const int16Array = new Int16Array(bytes.buffer);
    
    // Convert Int16 to Float32 [-1, 1]
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }

    // Create an AudioBuffer
    const buffer = this.ctx!.createBuffer(1, float32Array.length, 24000);
    buffer.copyToChannel(float32Array, 0);

    // Schedule playback
    const source = this.ctx!.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx!.destination);
    
    // Avoid gapless playback popping by scheduling slightly in the future if we're falling behind
    const now = this.ctx!.currentTime;
    if (this.nextStartTime < now) {
        this.nextStartTime = now + 0.05; // 50ms buffer to prevent starvation jitter
    }
    
    source.start(this.nextStartTime);
    this.nextStartTime += buffer.duration;

    this.activeSources.push(source);

    // Filter out finished sources to avoid memory accumulation
    const durationMs = buffer.duration * 1000;
    setTimeout(() => {
      this.activeSources = this.activeSources.filter(src => src !== source);
    }, durationMs + 200);
  }

  stop() {
    this.activeSources.forEach(source => {
      try {
        source.stop();
      } catch (e) {
        // already stopped or finished
      }
    });
    this.activeSources = [];
    if (this.ctx) {
      this.nextStartTime = this.ctx.currentTime + 0.05;
    } else {
      this.nextStartTime = 0;
    }
  }
}
