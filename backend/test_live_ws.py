"""Manual integration test for the Gemini Live /ws/live-translate endpoint.

Streams a pre-recorded Hindi PCM utterance into the WebSocket and prints the
input transcript, the translated text, and whether translated audio came back.
Run while the backend is up on 127.0.0.1:8000.
"""
import asyncio
import base64
import json
import sys

import websockets

PCM_PATH = "/tmp/hindi.pcm"
WS_URL = "ws://127.0.0.1:8000/ws/live-translate?source_lang=none&target_lang=en"
CHUNK = 3200  # 100ms of 16kHz mono s16le


async def main() -> None:
    with open(PCM_PATH, "rb") as f:
        pcm = f.read()
    print(f"[i] loaded {len(pcm)} bytes of PCM ({len(pcm)/32000:.1f}s)")

    async with websockets.connect(WS_URL, max_size=None) as ws:
        # 1. wait for ready
        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        print(f"[ready] {ready}")

        # 2. stream the utterance in 100ms chunks
        async def feed():
            for i in range(0, len(pcm), CHUNK):
                await ws.send(json.dumps({
                    "type": "audio_chunk",
                    "data": base64.b64encode(pcm[i:i + CHUNK]).decode(),
                }))
                await asyncio.sleep(0.1)
            # trailing silence so VAD fires end-of-speech
            silence = b"\x00" * CHUNK
            for _ in range(12):
                await ws.send(json.dumps({
                    "type": "audio_chunk",
                    "data": base64.b64encode(silence).decode(),
                }))
                await asyncio.sleep(0.1)
        feeder = asyncio.create_task(feed())

        audio_chunks = 0
        in_text = ""
        out_text = ""
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                t = msg.get("type")
                if t == "live_transcript":
                    in_text = msg.get("input_text") or in_text
                    out_text = msg.get("output_text") or out_text
                    print(f"[transcript] IN='{in_text}'  OUT='{out_text}'  "
                          f"in_fin={msg.get('input_finished')} out_fin={msg.get('output_finished')}")
                elif t == "audio_response":
                    audio_chunks += 1
                    if audio_chunks == 1:
                        print("[audio] first translated-audio chunk received")
                elif t == "error":
                    print(f"[ERROR] {msg.get('message')}")
                    break
                else:
                    print(f"[{t}] {msg}")
        except asyncio.TimeoutError:
            print("[i] no more messages (15s idle) — stopping")
        finally:
            feeder.cancel()

        print("\n===== RESULT =====")
        print(f"input (Hindi)      : {in_text!r}")
        print(f"translation (Eng)  : {out_text!r}")
        print(f"translated audio   : {audio_chunks} chunks  -> {'YES' if audio_chunks else 'NO'}")
        ok = bool(in_text) and bool(out_text) and audio_chunks > 0
        print(f"PASS: {ok}")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
