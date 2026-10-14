"""Labeled audio samples: synthetic speech for the four recording types the pipeline will meet.

  internal/analyst_voice_memo.wav   analyst dictates a risk review (risk_analyst_note)
  merchant/merchant_call.wav        two-speaker call: merchant rebuts a chargeback and reads a
                                    card number aloud (dispute_rebuttal; PCI test)
  merchant/voicemail_noisy.mp3      merchant voicemail over background noise, phone number spoken
                                    (no matching doc type -> review)
  internal/dictated_update.m4a      short dictated update (risk_analyst_note), AAC

Speech comes from macOS `say` when present, else espeak-ng. Each label carries the exact script
as `reference_transcript`: what a good recognizer (whisper.cpp, Transcribe) should return. The
`reference` transcriber replays it, so extraction can be tested apart from recognition quality."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from uif.providers.formats import Transcriber, TranscriptResult

SCRIPTS = {
    "internal/analyst_voice_memo.wav": {
        "source_group": "internal", "doc_type": "risk_analyst_note", "merchant_id": "M0002",
        "lines": [("Analyst", "Risk review voice memo. Case number R C two zero two six, four four one two. "
                              "Merchant, Ridgeline Outdoor Supply Inc. Analyst, P Raman. Review date, October fifth, "
                              "two thousand twenty six. The refund rate has climbed for three straight months. We also "
                              "saw bursts of small dollar authorizations from a handful of I P ranges. "
                              "Recommendation, reserve. Exposure estimate, one hundred eighty five thousand dollars.")],
        "fields": {"case_id": "RC-2026-4412", "merchant_name": "Ridgeline Outdoor Supply Inc", "analyst": "P. Raman",
                   "review_date": "2026-10-05", "risk_themes": ["card testing", "refund abuse"],
                   "recommended_action": "reserve", "exposure_estimate": 185000.0},
        "raw_identifiers": [],
    },
    "merchant/merchant_call.wav": {
        "source_group": "merchant", "doc_type": "dispute_rebuttal", "merchant_id": "M0001",
        "lines": [
            ("Agent", "Thank you for calling merchant disputes. Can I have the case number?"),
            ("Merchant", "Yes. It's C B two zero two six, eight one four two seven three. This is Blue Harbor Coffee "
                         "L L C, merchant I D eight zero zero zero, one two three four, five six seven eight."),
            ("Agent", "Thanks. I see a Visa chargeback, reason code thirteen point one, for two hundred forty eight "
                      "dollars and fifty cents, on a sale from August ninth, two thousand twenty six. "
                      "What is your rebuttal?"),
            ("Merchant", "The order was delivered to the cardholder's address on August twelfth. The order number is "
                         "O R D five five one two zero. For our records, the test card we used was four one one one, "
                         "one one one one, one one one one, one one one one."),
            ("Agent", "Please don't read card numbers on this line. Upload the invoice and the carrier proof of "
                      "delivery to the portal, and I will note that the order was delivered."),
        ],
        # nothing is attached on a phone call; invoice and proof of delivery are only promised
        "fields": {"case_number": "CB-2026-814273", "merchant_legal_name": "Blue Harbor Coffee LLC",
                   "mid": "800012345678", "card_network": "visa", "reason_code": "13.1", "dispute_amount": 248.50,
                   "transaction_date": "2026-08-09", "order_number": "ORD-55120", "evidence_types": [],
                   "rebuttal_basis": "delivered"},
        "raw_identifiers": ["4111 1111 1111 1111"],
    },
    "merchant/voicemail_noisy.mp3": {
        "source_group": "merchant", "doc_type": "unknown", "merchant_id": None,
        "lines": [("Caller", "Hi, this is Dana from Maple and Main Bakery. Our deposits for the last two days have "
                             "not arrived and we are short for payroll on Friday. Please call me back at four six "
                             "nine, five five five, zero one one zero. Thanks.")],
        "fields": {}, "raw_identifiers": ["469 555 0110"], "noise": True,
    },
    "internal/dictated_update.m4a": {
        "source_group": "internal", "doc_type": "risk_analyst_note", "merchant_id": "M0003",
        "lines": [("Analyst", "Quick update for the risk review on case R C two zero two six, seven seven zero one. "
                              "Merchant, Pinecrest Dental Group P L L C. Analyst, K Nguyen. Review date, October "
                              "seventh, two thousand twenty six. The chargeback ratio reached two point eight percent "
                              "last month. Recommendation, escalate. Exposure estimate, ninety two thousand five "
                              "hundred dollars.")],
        "fields": {"case_id": "RC-2026-7701", "merchant_name": "Pinecrest Dental Group PLLC", "analyst": "K. Nguyen",
                   "review_date": "2026-10-07", "risk_themes": ["chargeback spike"],
                   "recommended_action": "escalate", "exposure_estimate": 92500.0},
        "raw_identifiers": [],
    },
}

VOICES = {  # speaker -> (espeak-ng voice, macOS say voice)
    "Agent": ("en-us", "Samantha"), "Merchant": ("en-gb+f3", "Daniel"),
    "Analyst": ("en-us", "Alex"), "Caller": ("en-us+f2", "Karen"),
}


def tts_engine() -> str | None:
    if shutil.which("say"):
        return "say"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return "espeak"
    return None


def _speak(engine: str, speaker: str, text: str, dest: Path) -> None:
    espeak_voice, say_voice = VOICES.get(speaker, ("en-us", "Alex"))
    if engine == "say":
        aiff = dest.with_suffix(".aiff")
        r = subprocess.run(["say", "-v", say_voice, "-o", str(aiff), text], capture_output=True)
        if r.returncode != 0:  # voice not installed: default voice
            subprocess.run(["say", "-o", str(aiff), text], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1", str(dest)],
                       check=True)
    else:
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        subprocess.run([binary, "-v", espeak_voice, "-s", "150", "-w", str(dest), text], check=True, capture_output=True)


def _render(engine: str, lines: list[tuple[str, str]], dest: Path, noise: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (speaker, text) in enumerate(lines):
            seg = Path(tmp) / f"seg{i}.wav"
            _speak(engine, speaker, text, seg)
            norm = Path(tmp) / f"n{i}.wav"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(seg), "-ar", "16000", "-ac", "1",
                            "-af", "apad=pad_dur=0.5", str(norm)], check=True)
            parts.append(norm)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        joined = Path(tmp) / "joined.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(joined)], check=True)
        src = joined
        if noise:  # street/café noise under the voice
            noisy = Path(tmp) / "noisy.wav"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(joined), "-f", "lavfi", "-i",
                            "anoisesrc=color=pink:amplitude=0.06:sample_rate=16000:seed=7", "-filter_complex",
                            "[0:a][1:a]amix=inputs=2:duration=first:normalize=0", "-ac", "1", str(noisy)], check=True)
            src = noisy
        codec = {".wav": ["-c:a", "pcm_s16le"], ".mp3": ["-c:a", "libmp3lame", "-b:a", "48k"],
                 ".m4a": ["-c:a", "aac", "-b:a", "48k"]}[dest.suffix]
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", *codec,
                        str(dest)], check=True)


def reference_transcript(spec: dict) -> str:
    """Diarized like Amazon Transcribe output (spk_0, spk_1, ...): recognizers don't know who is the
    agent, and role names such as "Merchant:" would collide with field labels in the schemas."""
    lines = spec["lines"]
    speakers = list(dict.fromkeys(s for s, _ in lines))
    if len(speakers) > 1:
        return "\n".join(f"spk_{speakers.index(s)}: {t}" for s, t in lines)
    return " ".join(t for _, t in lines)


def generate_audio(out: str | Path) -> dict:
    out = Path(out)
    engine = tts_engine()
    if not engine:
        return {"out": str(out), "documents": 0,
                "skipped": "no text-to-speech engine: install espeak-ng (Linux) or run on macOS (`say`)"}
    if not shutil.which("ffmpeg"):
        return {"out": str(out), "documents": 0, "skipped": "ffmpeg is required"}
    for sub in ("merchant", "internal", "labels"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    made = {}
    for rel, spec in SCRIPTS.items():
        dest = out / rel
        _render(engine, spec["lines"], dest, spec.get("noise", False))
        label = {"file": rel, "source_group": spec["source_group"], "doc_type": spec["doc_type"],
                 "fields": spec["fields"], "merchant_id": spec["merchant_id"], "format": dest.suffix[1:],
                 "flags": ["audio"] + (["noise"] if spec.get("noise") else []), "tts_engine": engine,
                 "reference_transcript": reference_transcript(spec),
                 "raw_identifiers": [r.replace(" ", "") for r in spec["raw_identifiers"]]}
        (out / "labels" / f"{dest.name}.json").write_text(json.dumps(label, indent=2))
        made[rel] = f"{dest.stat().st_size:,} bytes"
    return {"out": str(out), "documents": len(made), "tts_engine": engine, "files": made}


class ReferenceTranscriber(Transcriber):
    """Replays the labelled script as the transcript: a stand-in for a good recognizer (whisper.cpp,
    Transcribe) so extraction can be tested apart from recognition quality. Test use only."""

    name = "reference"

    def __init__(self, labels_dir: str | Path):
        self.by_name = {}
        for p in Path(labels_dir).glob("*.json"):
            lab = json.loads(p.read_text())
            if lab.get("reference_transcript"):
                self.by_name[Path(lab["file"]).name] = lab["reference_transcript"]

    def available(self) -> bool:
        return bool(self.by_name)

    def transcribe(self, data: bytes, file_name: str) -> TranscriptResult:
        if file_name not in self.by_name:
            raise NotImplementedError(f"audio: no reference transcript for {file_name}")
        return TranscriptResult(self.by_name[file_name], self.name)
