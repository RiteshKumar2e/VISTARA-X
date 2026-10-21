"""Command pipeline: transcript -> parsed intent -> validation -> (confirmation) -> execution.

Stop, pause and resume run immediately: they only ever make the robot do less. A new
destination is validated against the map (known place, safe target, route exists) and
waits for the user's confirmation unless trusted mode is on. Every command is kept in
a history with its transcript, language, intent, validation and response text.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from ..simulation.engine import ACTIVE, CommandError
from .parser import ParsedCommand, parse

CAREFUL = {"safety_margin": 0.30, "max_speed": 0.6}
SLOW_SPEED = 0.5

# Response templates: en, hi (Devanagari), hi-Latn (Hinglish).
MSG = {
    "confirm": {
        "en": "Go to {place}? Route found: {length:.1f} m. Press Confirm to start.",
        "hi": "{place} तक जाएँ? रास्ता मिला: {length:.1f} मीटर। शुरू करने के लिए Confirm दबाएँ।",
        "hi-Latn": "{place} tak jaana hai? Raasta mila: {length:.1f} m. Shuru karne ke liye Confirm dabao.",
    },
    "no_route": {
        "en": "{place} is a known place, but no collision-free route to it exists right now. If you confirm, the robot will report Blocked instead of moving.",
        "hi": "{place} एक जानी हुई जगह है, लेकिन अभी वहाँ तक कोई सुरक्षित रास्ता नहीं है। Confirm करने पर रोबोट चलेगा नहीं, Blocked बताएगा।",
        "hi-Latn": "{place} jaani-pehchaani jagah hai, lekin abhi wahan tak koi safe raasta nahi hai. Confirm karoge toh robot chalega nahi, Blocked batayega.",
    },
    "started": {
        "en": "Navigating to {place}.",
        "hi": "{place} की ओर जा रहा हूँ।",
        "hi-Latn": "{place} ki taraf ja raha hoon.",
    },
    "invalid_target": {
        "en": "{place} cannot be used as a destination now: {reason}",
        "hi": "{place} अभी मंज़िल नहीं बन सकता: {reason}",
        "hi-Latn": "{place} abhi destination nahi ban sakta: {reason}",
    },
    "ambiguous": {
        "en": "Which place did you mean: {options}?",
        "hi": "आप किस जगह की बात कर रहे हैं: {options}?",
        "hi-Latn": "Kaunsi jagah: {options}?",
    },
    "unknown_destination": {
        "en": "I don't know that place. Known places: {places}.",
        "hi": "मुझे यह जगह नहीं पता। जानी हुई जगहें: {places}।",
        "hi-Latn": "Ye jagah mujhe nahi pata. Jaani-pehchaani jagahein: {places}.",
    },
    "no_destination": {
        "en": "Where should the robot go? Known places: {places}.",
        "hi": "रोबोट को कहाँ जाना है? जानी हुई जगहें: {places}।",
        "hi-Latn": "Robot ko kahan jaana hai? Jaani-pehchaani jagahein: {places}.",
    },
    "not_understood": {
        "en": "Sorry, I did not understand. Try \"Take the robot to the reception\" or \"Stop\".",
        "hi": "माफ़ कीजिए, समझ नहीं आया। जैसे बोलें: \"रोबोट को रिसेप्शन तक ले जाओ\" या \"रुको\"।",
        "hi-Latn": "Maaf kijiye, samajh nahi aaya. Aise bolo: \"Robot ko reception tak le jao\" ya \"Ruko\".",
    },
    "empty": {
        "en": "No command text was received.",
        "hi": "कोई कमांड नहीं मिली।",
        "hi-Latn": "Koi command nahi mili.",
    },
    "stopped": {
        "en": "Stopped. The robot is halted.",
        "hi": "रुक गया। रोबोट रोक दिया गया है।",
        "hi-Latn": "Ruk gaya. Robot rok diya gaya hai.",
    },
    "stop_idle": {
        "en": "Stop received. The robot was not moving.",
        "hi": "रुकने का आदेश मिला। रोबोट पहले से रुका हुआ था।",
        "hi-Latn": "Stop mila. Robot pehle se ruka hua tha.",
    },
    "paused": {
        "en": "Paused. Say \"resume\" to continue.",
        "hi": "रोक दिया। आगे बढ़ने के लिए \"फिर से चलो\" कहें।",
        "hi-Latn": "Pause kar diya. Aage badhne ke liye \"phir se chalo\" bolo.",
    },
    "resumed": {
        "en": "Resuming the mission.",
        "hi": "मिशन फिर से शुरू।",
        "hi-Latn": "Mission phir se shuru.",
    },
    "nothing_to_pause": {
        "en": "Nothing to pause: no mission is running.",
        "hi": "रोकने के लिए कोई मिशन नहीं चल रहा।",
        "hi-Latn": "Pause karne ke liye koi mission nahi chal raha.",
    },
    "nothing_to_resume": {
        "en": "Nothing to resume: the mission is not paused.",
        "hi": "फिर से शुरू करने के लिए कोई रुका हुआ मिशन नहीं है।",
        "hi-Latn": "Resume karne ke liye koi paused mission nahi hai.",
    },
    "cancelled": {
        "en": "Cancelled. The robot was not sent.",
        "hi": "रद्द किया। रोबोट नहीं भेजा गया।",
        "hi-Latn": "Cancel kar diya. Robot nahi bheja gaya.",
    },
    "failed": {
        "en": "Could not start: {reason}",
        "hi": "शुरू नहीं हो सका: {reason}",
        "hi-Latn": "Shuru nahi ho saka: {reason}",
    },
}

NOTE = {
    "careful": {
        "en": " Careful mode: 0.30 m safety margin, max 0.6 m/s.",
        "hi": " सावधान मोड: 0.30 मीटर सुरक्षा दूरी, अधिकतम 0.6 मीटर/सेकंड।",
        "hi-Latn": " Careful mode: 0.30 m safety margin, max 0.6 m/s.",
    },
    "slow": {
        "en": " Slow mode: max 0.5 m/s.",
        "hi": " धीमा मोड: अधिकतम 0.5 मीटर/सेकंड।",
        "hi-Latn": " Slow mode: max 0.5 m/s.",
    },
}


def say(key: str, lang: str, **kw) -> str:
    table = MSG[key]
    return table.get(lang, table["en"]).format(**kw)


class CommandService:
    def __init__(self, engine):
        self.engine = engine
        self.history: deque[dict] = deque(maxlen=50)
        self._id = 0
        self._lock = threading.Lock()
        self._restore: dict | None = None  # parameters to restore after a constrained mission

    # ------------------------------------------------------------ helpers
    def _places(self):
        return self.engine.scenario.places

    def _place_name(self, dest: dict | None, lang: str) -> str:
        if not dest:
            return ""
        if "key" in dest:
            return dest["name_hi"] if lang == "hi" else dest["name"]
        return f"({dest['x']:.1f}, {dest['y']:.1f})"

    def _place_list(self, lang: str) -> str:
        sep = ", "
        return sep.join(p.name_hi if lang == "hi" else p.name for p in self._places())

    def _restore_params(self) -> None:
        if self._restore:
            self.engine.configure(**self._restore)
            self._restore = None

    def _apply_constraints(self, constraints: dict) -> None:
        self._restore_params()
        if not constraints:
            return
        p = self.engine.params
        self._restore = {"max_speed": p["max_speed"], "safety_margin": p["safety_margin"]}
        speed = p["max_speed"]
        margin = None
        if constraints.get("careful"):
            speed = min(speed, CAREFUL["max_speed"])
            margin = max(p["safety_margin"], CAREFUL["safety_margin"])
        if constraints.get("slow"):
            speed = min(speed, SLOW_SPEED)
        self.engine.configure(max_speed=speed, safety_margin=margin)

    def _record(self, text: str, source: str, stt: dict | None, cmd: ParsedCommand) -> dict:
        self._id += 1
        return {
            "id": self._id,
            "time": time.strftime("%H:%M:%S"),
            "sim_time": round(self.engine.sim_time, 1),
            "source": source,
            "transcript": text,
            "language": cmd.language,
            "speech": stt,
            "intent": {
                "type": cmd.intent,
                "destination": cmd.destination,
                "constraints": cmd.constraints,
                "keywords": cmd.matched,
            },
            "status": "pending",
            "validation": None,
            "response": None,
        }

    def _respond(self, rec: dict, key: str, status: str, **kw) -> dict:
        lang = rec["language"]
        text = say(key, lang, **kw)
        for c in rec["intent"]["constraints"]:
            if status in ("awaiting_confirmation", "executed") and rec["intent"]["type"] in ("navigate", "return_home"):
                text += NOTE[c].get(lang, NOTE[c]["en"])
        rec["status"] = status
        rec["response"] = {"language": lang, "text": text}
        return rec

    # ------------------------------------------------------------ pipeline
    def interpret(self, text: str, source: str = "text", stt: dict | None = None, trusted: bool = False) -> dict:
        with self._lock:
            cmd = parse(text, self._places())
            rec = self._record(text, source, stt, cmd)
            self.history.append(rec)
            lang = cmd.language
            if cmd.intent == "stop":
                return self._do_stop(rec)
            if cmd.intent == "pause":
                return self._do_simple(rec, self.engine.pause, "paused", "nothing_to_pause")
            if cmd.intent == "resume":
                return self._do_simple(rec, self.engine.resume, "resumed", "nothing_to_resume")
            if cmd.issue == "ambiguous":
                sep = " or " if lang == "en" else (" या " if lang == "hi" else " ya ")
                return self._respond(rec, "ambiguous", "needs_clarification", options=sep.join(cmd.candidates))
            if cmd.issue in ("unknown_destination", "no_destination"):
                return self._respond(rec, cmd.issue, "needs_clarification", places=self._place_list(lang))
            if cmd.issue in ("not_understood", "empty"):
                return self._respond(rec, cmd.issue, "rejected")

            # navigate / return_home with a destination: validate before anything moves.
            dest = cmd.destination
            name = self._place_name(dest, lang)
            check = self.engine.preview_route(dest["x"], dest["y"])
            rec["validation"] = check
            if not check["valid"]:
                return self._respond(rec, "invalid_target", "rejected", place=name, reason=check["message"])
            if not check["reachable"]:
                return self._respond(rec, "no_route", "awaiting_confirmation", place=name)
            if trusted:
                return self._execute(rec)
            return self._respond(rec, "confirm", "awaiting_confirmation", place=name, length=check["length"])

    def _do_stop(self, rec: dict) -> dict:
        # Restore any per-mission limits only after the robot has been halted.
        moving = self.engine.status in ACTIVE or self.engine.status == "paused"
        self.engine.emergency_stop()
        self._respond(rec, "stopped" if moving else "stop_idle", "executed")
        self._restore_params()
        return rec

    def _do_simple(self, rec: dict, action, ok_key: str, fail_key: str) -> dict:
        try:
            action()
            return self._respond(rec, ok_key, "executed")
        except CommandError:
            return self._respond(rec, fail_key, "rejected")

    def _find(self, cid: int) -> dict:
        rec = next((r for r in self.history if r["id"] == cid), None)
        if rec is None:
            raise CommandError("not_found", f"No command #{cid}", 404)
        if rec["status"] != "awaiting_confirmation":
            raise CommandError("not_pending", f"Command #{cid} is {rec['status']}, not awaiting confirmation")
        return rec

    def confirm(self, cid: int) -> dict:
        with self._lock:
            rec = self._find(cid)
            dest = rec["intent"]["destination"]
            # Re-validate: the world may have changed since the command was parsed.
            check = self.engine.preview_route(dest["x"], dest["y"])
            rec["validation"] = check
            if not check["valid"]:
                return self._respond(rec, "invalid_target", "rejected", place=self._place_name(dest, rec["language"]),
                                     reason=check["message"])
            return self._execute(rec)

    def cancel(self, cid: int) -> dict:
        with self._lock:
            rec = self._find(cid)
            return self._respond(rec, "cancelled", "cancelled")

    def _execute(self, rec: dict) -> dict:
        dest = rec["intent"]["destination"]
        name = self._place_name(dest, rec["language"])
        eng = self.engine
        try:
            self._apply_constraints(rec["intent"]["constraints"])
            eng.set_target(dest["x"], dest["y"])
            if eng.status == "paused":
                eng.resume()
            elif eng.status not in ACTIVE:
                eng.navigate()
            # An active mission replans to the new target by itself (set_target).
        except CommandError as exc:
            self._restore_params()
            return self._respond(rec, "failed", "failed", reason=exc.message)
        rec["executed_mission"] = eng.mission_id
        return self._respond(rec, "started", "executed", place=name)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.history)
