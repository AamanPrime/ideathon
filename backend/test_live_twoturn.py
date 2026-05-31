"""Two-turn integration test in a SINGLE connection.

Turn 1: Hindi (customer)  -> expect English text + audio.
Turn 2: English (staff)    -> expect Hindi text + audio (reverse direction).

Validates: continuous-receive fix (multi-turn), bidirectional audio, and
language memory (staff English routed back to the customer's Hindi).
"""
import asyncio
import base64
import json

import websockets

WS_URL = "ws://127.0.0.1:8000/ws/live-translate?source_lang=none&target_lang=en"
CHUNK = 3200


def load(path):
    with open(path, "rb") as f:
        return f.read()


async def stream_utterance(ws, pcm, tail_silence=14):
    for i in range(0, len(pcm), CHUNK):
        await ws.send(json.dumps({"type": "audio_chunk",
                                  "data": base64.b64encode(pcm[i:i + CHUNK]).decode()}))
        await asyncio.sleep(0.1)
    sil = b"\x00" * CHUNK
    for _ in range(tail_silence):
        await ws.send(json.dumps({"type": "audio_chunk",
                                  "data": base64.b64encode(sil).decode()}))
        await asyncio.sleep(0.1)


async def collect(ws, idle=10):
    """Collect transcript+audio until idle seconds pass with no message."""
    in_text, out_text, audio = "", "", 0
    while True:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=idle))
        except asyncio.TimeoutError:
            break
        t = msg.get("type")
        if t == "live_transcript":
            in_text = msg.get("input_text") or in_text
            out_text = msg.get("output_text") or out_text
        elif t == "audio_response":
            audio += 1
        elif t == "error":
            print(f"  [ERROR] {msg.get('message')}")
            break
    return in_text, out_text, audio


async def main():
    hindi = load("/tmp/hindi.pcm")
    eng = load("/tmp/eng.pcm")
    async with websockets.connect(WS_URL, max_size=None) as ws:
        print("[ready]", json.loads(await asyncio.wait_for(ws.recv(), timeout=30)))

        # ---- Turn 1: Hindi customer ----
        await stream_utterance(ws, hindi)
        in1, out1, aud1 = await collect(ws)
        print(f"\nTURN 1 (Hindi -> English)")
        print(f"  in  : {in1!r}")
        print(f"  out : {out1!r}")
        print(f"  audio chunks: {aud1}")

        # ---- Turn 2: English staff (same connection) ----
        await stream_utterance(ws, eng)
        in2, out2, aud2 = await collect(ws)
        print(f"\nTURN 2 (English -> Hindi)")
        print(f"  in  : {in2!r}")
        print(f"  out : {out2!r}")
        print(f"  audio chunks: {aud2}")

        t1 = bool(in1) and bool(out1) and aud1 > 0
        t2 = bool(in2) and bool(out2) and aud2 > 0
        # turn 2 output should contain Devanagari (Hindi) characters
        hindi_out = any('ऀ' <= c <= 'ॿ' for c in out2)
        print("\n===== RESULT =====")
        print(f"  Turn1 (customer->staff, audio): {'PASS' if t1 else 'FAIL'}")
        print(f"  Turn2 fired at all (multi-turn): {'PASS' if (in2 or out2) else 'FAIL'}")
        print(f"  Turn2 (staff->customer, audio) : {'PASS' if t2 else 'FAIL'}")
        print(f"  Turn2 output is Hindi script    : {'PASS' if hindi_out else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
