"""Two-turn Gujarati<->English test in a single connection.

Turn 1: Gujarati (customer) -> expect English text + audio.
Turn 2: English (staff)     -> expect Gujarati text + audio (language memory).
"""
import asyncio
import base64
import json

import websockets

WS_URL = "ws://127.0.0.1:8000/ws/live-translate?source_lang=none&target_lang=en"
CHUNK = 3200


def load(p):
    with open(p, "rb") as f:
        return f.read()


async def stream_utterance(ws, pcm, tail=14):
    for i in range(0, len(pcm), CHUNK):
        await ws.send(json.dumps({"type": "audio_chunk",
                                  "data": base64.b64encode(pcm[i:i + CHUNK]).decode()}))
        await asyncio.sleep(0.1)
    sil = b"\x00" * CHUNK
    for _ in range(tail):
        await ws.send(json.dumps({"type": "audio_chunk",
                                  "data": base64.b64encode(sil).decode()}))
        await asyncio.sleep(0.1)


async def collect(ws, idle=10):
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
    guj = load("/tmp/guj.pcm")
    eng = load("/tmp/eng.pcm")
    async with websockets.connect(WS_URL, max_size=None) as ws:
        print("[ready]", json.loads(await asyncio.wait_for(ws.recv(), timeout=30)))

        await stream_utterance(ws, guj)
        in1, out1, aud1 = await collect(ws)
        print(f"\nTURN 1 (Gujarati -> English)\n  in : {in1!r}\n  out: {out1!r}\n  audio: {aud1}")

        await stream_utterance(ws, eng)
        in2, out2, aud2 = await collect(ws)
        print(f"\nTURN 2 (English -> Gujarati)\n  in : {in2!r}\n  out: {out2!r}\n  audio: {aud2}")

        guj_in = any('઀' <= c <= '૿' for c in in1)
        guj_out = any('઀' <= c <= '૿' for c in out2)
        print("\n===== RESULT =====")
        print(f"  Turn1 input is Gujarati script  : {'PASS' if guj_in else 'FAIL'}")
        print(f"  Turn1 (cust->staff, eng + audio): {'PASS' if (out1 and aud1) else 'FAIL'}")
        print(f"  Turn2 fired (multi-turn)        : {'PASS' if (in2 or out2) else 'FAIL'}")
        print(f"  Turn2 (staff->cust, audio)      : {'PASS' if aud2 else 'FAIL'}")
        print(f"  Turn2 output is Gujarati script : {'PASS' if guj_out else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
