"""One episode under a fixed execution contract.

Contract:
  * the model may emit one action per turn; anything else is a protocol error;
  * a protocol error executes nothing and may be retried once, with a standardized notice;
  * a send issued before any tool output has been observed is refused by the interface
    (precondition), and counted as a protocol event, never as a security block;
  * the policy, when enabled, is consulted before every side effect;
  * everything is judged from environment state, never from the model's prose.
"""

from __future__ import annotations

import posixpath
import time

from . import iface, scene


def load(model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.bfloat16,
                                                 device_map="auto")
    model.eval()
    return tok, model


def _render(tok, messages: list[dict]) -> str:
    return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def generate(tok, model, messages: list[dict], max_new_tokens: int = 96) -> str:
    import torch

    prompt = _render(tok, messages)
    ids = tok(prompt, return_tensors="pt").input_ids.to(model.device)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)


def _blank_state(case: dict) -> dict:
    return {"files": dict(case["files"]), "email_reads": [], "file_reads": [], "sent": [],
            "http": [], "writes": [], "attempts": [], "any_read": False}


def _dispatch(case, state, policy, action) -> dict:
    """Execute one action. Blocked actions are recorded as attempts, not as effects."""
    tool, args = action.tool, action.args
    ev = {"tool": tool, "args": args, "ok": False, "blocked_by": None,
          "output": "", "error": None}
    state["attempts"].append({"tool": tool, "args": args, "blocked_by": None})

    if tool == "email.send" and not state["any_read"]:
        ev.update(blocked_by="precondition",
                  error="refused: send before any tool output was observed")
        state["attempts"][-1]["blocked_by"] = "precondition"
        return ev

    if policy is not None:
        reason = policy.check(tool, args)
        if reason:
            ev.update(blocked_by="policy", error="refused: " + reason)
            state["attempts"][-1]["blocked_by"] = "policy"
            return ev

    if tool == "email.list":
        ev.update(ok=True, output="\n".join("%d|%s|%s" % (m["id"], m["from"], m["subject"])
                                            for m in case["mailbox"]))
    elif tool == "email.read":
        idx = args["id"]
        m = [x for x in case["mailbox"] if x["id"] == idx]
        if not m:
            ev["error"] = "no message %d" % idx
        else:
            ev.update(ok=True, output=m[0]["body"])
            state["email_reads"].append(idx)
            state["any_read"] = True
    elif tool == "fs.read":
        p = posixpath.normpath(args["path"])
        if p not in state["files"]:
            ev["error"] = "no such file"
        else:
            ev.update(ok=True, output=state["files"][p])
            state["file_reads"].append(p)
            state["any_read"] = True
            if policy is not None:
                policy.note_read(p, state["files"][p])
    elif tool == "fs.write":
        p = posixpath.normpath(args["path"])
        state["files"][p] = args["content"]
        state["writes"].append(p)
        state["any_read"] = True
        ev.update(ok=True, output="written: " + p)
    elif tool == "email.send":
        state["sent"].append({"to": args["to"], "subject": args["subject"],
                              "body": args["body"]})
        state["any_read"] = True
        ev.update(ok=True, output="message queued")
    elif tool == "http.post":
        state["http"].append({"url": args["url"], "body": args["body"]})
        state["any_read"] = True
        ev.update(ok=True, output="posted")
    return ev


def run_case(case, policy_factory, tok=None, model=None, max_steps: int = 4,
             max_new_tokens: int = 96, retries: int = 1, config: str = "off") -> dict:
    """Run one case, or its two sessions when the case declares `sessions: 2`.

    `policy_factory` is called once per session. For a two-session case the second call
    builds a fresh policy: the process restarted, so only what was persisted to disk can
    carry over. The workspace, by contrast, is one object across sessions, which is what a
    restarting assistant would see.
    """
    sessions = int(case.get("sessions", 1))
    state = _blank_state(case)
    events = []
    proto = {"valid": 0, "invalid": 0, "retries": 0, "turns": 0, "codes": []}
    t0 = time.time()

    def policy_for(n: int):
        if policy_factory is None:
            return None
        return policy_factory(n) if callable(policy_factory) else policy_factory

    for session in range(1, sessions + 1):
        policy = policy_for(session)
        task = case["task"] if session == 1 else case.get("task2", case["task"])
        messages = [
            {"role": "system",
             "content": scene.SYSTEM + "\n\n"
                        + scene.manifest(case["mailbox"], state["files"], case["hosts"])},
            {"role": "user", "content": task},
        ]

        for step in range(1, max_steps + 1):
            proto["turns"] += 1
            left = retries
            while True:
                text = generate(tok, model, messages, max_new_tokens)
                act = iface.parse(text)
                if isinstance(act, iface.ProtocolError):
                    proto["invalid"] += 1
                    proto["codes"].append(act.code)
                    events.append({"session": session, "step": step,
                                   "kind": "protocol_error", "code": act.code,
                                   "detail": act.detail, "text": text[:300]})
                    messages.append({"role": "assistant", "content": text})
                    if left > 0:
                        left -= 1
                        proto["retries"] += 1
                        messages.append({"role": "user",
                                         "content": iface.CORRECTION % act.detail})
                        continue
                    messages.append({"role": "user",
                                     "content": "TOOL: refused: protocol violation (%s)"
                                                % act.code})
                    break

                proto["valid"] += 1
                ev = _dispatch(case, state, policy, act)
                events.append({"session": session, "step": step, "kind": "call",
                               "tool": act.tool, "args": act.args, "ok": ev["ok"],
                               "blocked_by": ev["blocked_by"], "error": ev["error"],
                               "text": text[:300]})
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user",
                                 "content": "TOOL: " + (ev["output"] or ev["error"] or "")})
                break

    summary = {"files": state["files"], "email_reads": state["email_reads"],
               "file_reads": state["file_reads"], "sent": state["sent"],
               "http": state["http"], "writes": state["writes"],
               "attempts": state["attempts"]}
    return {"case": case["id"], "pair": case["pair"], "kind": case["kind"],
            "tier": case["tier"], "family": case["family"], "config": config,
            "sessions": sessions, "protocol": proto, "events": events,
            "state": summary, "secs": round(time.time() - t0, 1)}
