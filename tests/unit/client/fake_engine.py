"""A stand-in for the engine process, for the client's tests (ADR-0011).

It answers as the engine does, with the standard library only, so that it shares no code with
the client, and it misbehaves on cue. The cue is the model path of `initialize`, the condition
of `rewrite`, or the text of the first statement of `judge`:

- "exit": exit at once with code 3, as llama.cpp's abort() does;
- "half": write half a message, then exit;
- "hang": never answer;
- "garbage": answer with a line that is not a message;
- "another id": answer as if to another request;
- "exit later": answer, then exit a moment later, while idle;
- "deaf": answer, then read nothing more: neither `shutdown` nor the end of the input;
- "internal", "no model", "no memory", "too long": the engine's errors -32603, -32003,
  -32004 and -32005.

Otherwise d is the statement's id plus the length of the title, and the statement is the
condition inside "The user: ….". The first argument, when given, is the protocol version it
speaks. Its first line on stderr is "pid" and its process id; its second is not ASCII.
"""

import json
import os
import sys
import time
from typing import Any

PROTOCOL = int(sys.argv[1]) if len(sys.argv) > 1 else 1
ERRORS = {
    "internal": (-32603, "Internal error"),
    "mismatch": (-32002, "Protocol mismatch"),
    "no model": (-32003, "Model cannot be loaded"),
    "no memory": (-32004, "GPU out of memory"),
    "too long": (-32005, "Text too long for the context"),
}
FOREVER = 3600


def answer(request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The cue of a request, and the answer to it."""
    params = request["params"]
    cue = ""
    result: object = None
    match request["method"]:
        case "initialize":
            cue = params["model_path"] if params["protocol"] == PROTOCOL else "mismatch"
            result = {
                "protocol": PROTOCOL,
                "engine_version": "0.0.1",
                "llama_cpp_build": "b1",
                "gpu": "Fake GPU",
                "free_vram_bytes": 1 << 30,
                "model_type": "fake",
                "prompt_versions": {"judge": 3, "rewrite": 4},
            }
        case "judge":
            statements = params["statements"]
            cue = statements[0]["text"]
            title = params["context"]["title"]
            result = {
                "scores": [{"id": s["id"], "d": s["id"] + len(title)} for s in statements],
                "timings": {"total_seconds": 0.01},
            }
        case "rewrite":
            cue = params["condition"]
            result = {
                "statement": f"The user: {cue}.",
                "prompt_version": 4,
                "timings": {"total_seconds": 0.01},
            }
    if cue in ERRORS:
        code, message = ERRORS[cue]
        error = {"code": code, "message": message, "data": {"detail": cue, "retry": False}}
        return cue, {"jsonrpc": "2.0", "id": request["id"], "error": error}
    return cue, {"jsonrpc": "2.0", "id": request["id"], "result": result}


def main() -> None:
    sys.stderr.buffer.write(f"pid {os.getpid()}\nè partito\n".encode())
    sys.stderr.buffer.flush()
    output = sys.stdout.buffer
    for line in sys.stdin.buffer:
        cue, response = answer(json.loads(line))
        if cue == "exit":
            os._exit(3)
        if cue == "half":
            output.write(b'{"jsonrpc": "2.0", ')
            output.flush()
            os._exit(3)
        if cue == "hang":
            time.sleep(FOREVER)
        if cue == "another id":
            response["id"] += 1
        message = b"this is not a message" if cue == "garbage" else json.dumps(response).encode()
        output.write(message + b"\n")
        output.flush()
        if cue == "exit later":
            time.sleep(0.2)
            return
        if cue == "deaf":
            time.sleep(FOREVER)


if __name__ == "__main__":
    main()
