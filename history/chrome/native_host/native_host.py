#!/usr/bin/env python3.12

import sys
import json
import struct
import traceback
import requests
import time
import threading

SERENITY_ROUTE = "http://192.168.0.111:2406/serenity"
HANDOFF_REQUEST_INTERVAL = 2  # seconds

last_handoff_request = 0


# ---------- Native messaging helpers ----------
def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    message_length = struct.unpack('I', raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode('utf-8')
    return json.loads(message)


def send_message(message):
    encoded = json.dumps(message).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# ---------- Existing behavior (UNCHANGED) ----------
def handle_extension_message(msg):
    url = msg.get("url")

    try:
        requests.post(SERENITY_ROUTE + "/handoff", data={"url": url})
        send_message({"status": "ok"})
    except Exception as e:
        send_message({
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc()
        })


# ---------- New: Active polling loop ----------
def poll_handoff_requests():
    global last_handoff_request

    while True:
        ts = time.time()

        if ts - last_handoff_request > HANDOFF_REQUEST_INTERVAL:
            try:
                response = requests.get(
                    SERENITY_ROUTE + "/handoff/request/pending",
                    timeout=1
                )

                if response.status_code == 200:
                    send_message({
                        "intent": "handoff-request",
                        "timestamp": int(ts)
                    })

            except Exception:
                pass


            last_handoff_request = ts

        time.sleep(HANDOFF_REQUEST_INTERVAL)  # small delay to avoid CPU burn


# ---------- Main ----------
def main():
    # Start polling thread (non-blocking)
    threading.Thread(target=poll_handoff_requests, daemon=True).start()

    # Main loop: handle messages from extension
    while True:
        msg = read_message()
        if msg is None:
            break

        handle_extension_message(msg)


if __name__ == "__main__":
    main()