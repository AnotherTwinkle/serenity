from flask import Flask
from flask import request
from queue import Queue
import socket
import threading
import time
import random
import os
import base64
import subprocess
import tempfile
import pyperclip
import pyperclipimg as pci

app = Flask(__name__)
PORT = 2407
PACKET_QUEUE = Queue()

# --- HTTP ROUTES ---
@app.route("/")
def index():
    return "Flask server is running"

@app.route("/ping")
def ping():
    return {"status": "ok"}

# Common
def prepare_packet(intent, packet, lifetime = 0):
    packet = {
        "intent" : intent,
        "data" : packet,
        "timestamp" : int(time.time()),
        "nonce" : f"{int(time.time() * 100)}{random.randint(100, 999)}",
        "lifetime" : lifetime
    }

    return packet

def post_packet(packet):
    PACKET_QUEUE.put(packet)

# --- Handoff ---
HANDOFF_REQUEST_LAST_TIME = 0
HANDOFF_REQUEST_PENDING = False
@app.post("/serenity/handoff")
def post_handoff():
    url = request.form['url']
    packet = {
        "url" : url
    }
    packet = prepare_packet(intent = "handoff", packet = packet, lifetime = 10) # 10s lifetime for handoffs
    post_packet(packet)
    return '', 200

@app.post("/serenity/handoff/request")
def post_handoff_request():
    global HANDOFF_REQUEST_PENDING, HANDOFF_REQUEST_LAST_TIME
    HANDOFF_REQUEST_LAST_TIME = int(time.time())
    HANDOFF_REQUEST_PENDING = True
    return '', 200

@app.get("/serenity/handoff/request/pending")
def get_handoff_request_pending():
    global HANDOFF_REQUEST_PENDING
    ts = int(time.time())

    if ts - HANDOFF_REQUEST_LAST_TIME >= 10:
        HANDOFF_REQUEST_PENDING = False

    if HANDOFF_REQUEST_PENDING:
        HANDOFF_REQUEST_PENDING = False
        return '', 200
    else:
        return '', 404

# --- Clipboard ---
@app.post("/serenity/clipboard/text")
def post_clipboard_text():
    text = request.form['content']
    print("COPYING ", text)
    pyperclip.copy(text)
    return 'OK', 200

@app.post("/serenity/clipboard/file")
def post_clipboard_file():
    data = request.get_json()
    if not data or "filename" not in data or "data" not in data:
        return "Missing filename or b64 data", 400

    filename = os.path.basename(data["filename"])
    try:
        file_bytes = base64.b64decode(data["data"])
        file_bytes = base64.b64decode(file_bytes) # why? no fucking idea
    except Exception:
        return "Invalid base64 data", 400

    # save to temp file
    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        # this will copy the image at tmp_path to clipboard
        pci.copy(tmp_path)
        os.system(f'notify-send "Image Recieved" "{filename}"')
    except Exception as e:
        raise e
        return f"Clipboard error: {e}", 500
    finally:
        pass
        # os.unlink(tmp_path)

    return f"OK", 200

@app.post("/serenity/file")
def post_file():
    filepath = request.form['filepath']
    print(filepath)
    os.system(f'adb pull \"{filepath}\" /home/fijaj/Documents/cpnew/ttlgs')
    return "OK", 200

# --- Device Control ---
@app.post("/serenity/lock/client")
def lock_client():
    post_packet(prepare_packet(
        "lock",
        {},
        10
    ))
    return '', 200

# --- Polling ---
AIRDROP_TEST_DONE = False
@app.get("/serenity/queue")
def get_queue():
    global AIRDROP_TEST_DONE

    if not AIRDROP_TEST_DONE:
        filename = "mj.jpg"
        with open(filename, 'rb') as f:
            filedata = f.read()

        data = {
            "filename" : filename,
            "data" : base64.b64encode(filedata).decode("utf-8")
        }

        packet = prepare_packet(
            "airdrop",
            data,
            10
        )

        post_packet(packet)

        AIRDROP_TEST_DONE = True

    if PACKET_QUEUE.qsize() == 0:
        return {"intent" : None}

    while True:
        packet = PACKET_QUEUE.get()
        if packet['lifetime'] != 0 and packet['timestamp'] + packet['lifetime'] < int(time.time()):
            continue

        if packet['intent'] == 'handoff':
            os.system(f'notify-send "Handed off" "{packet['data']['url']}"')
        return packet


# --- STARTUP ---
if __name__ == "__main__":
    # run flask server
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    app.run(host="0.0.0.0", port=PORT)
