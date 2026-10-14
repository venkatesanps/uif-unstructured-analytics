"""Audio end to end. Extraction is tested with reference transcripts (a stand-in for a good
recognizer) so it runs anywhere; real recognition (pocketsphinx) and generation (espeak-ng / macOS
`say`) run only where those engines are installed."""

import json
import shutil
from pathlib import Path

import pytest

from tests.conftest import make_ctx
from uif import parity
from uif.contracts import GuardedDoc, NormalizedDoc, Page, ReviewStatus, Validated
from uif.evals import evaluate, gate
from uif.providers import formats as fmt
from uif.providers.local import LocalOCR, RegexGuard
from uif.steps.validate import value_in_quote
from uif.values import spoken_date, spoken_digits_to_numerals, spoken_numbers, to_money

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "samples" / "audio"


# ----------------------------------------------------------------------------- spoken language

@pytest.mark.parametrize("text,expected", [
    ("one hundred eighty five thousand dollars", 185000), ("ninety two thousand five hundred dollars", 92500),
    ("two hundred forty eight dollars and fifty cents", 248.5), ("two point eight percent", 2.8),
    ("reason code thirteen point one", 13.1),
])
def test_spoken_numbers(text, expected):
    assert spoken_numbers(text)[0] == expected


def test_spoken_dates_and_money():
    assert spoken_date("Review date, October fifth, two thousand twenty six.") == "2026-10-05"
    assert spoken_date("March twenty first, twenty twenty six") == "2026-03-21"
    assert spoken_date("on August twelfth") is None  # no year said: don't invent one
    assert to_money("one hundred twenty thousand dollars") == 120000.0


def test_numbers_read_aloud_become_visible_to_the_guard():
    text = spoken_digits_to_numerals("the card was four one one one, one one one one, one one one one, one one one one. "
                                     "Call me at four six nine, five five five, zero one one zero. It took three months.")
    out, findings = RegexGuard("s").scan([Page(page=1, text=text)])
    assert sorted(f.kind for f in findings) == ["pan", "phone"]
    assert "three months" in out[0].text  # single number words stay words


def test_validator_accepts_spoken_identifiers_but_not_wrong_ones():
    assert value_in_quote("string", "CB-2026-814273", "It's C B 2026 814273.")
    assert value_in_quote("string", "13.1", "reason code thirteen point one")
    assert value_in_quote("string", "Blue Harbor Coffee LLC", "This is Blue Harbor Coffee L L C")
    assert not value_in_quote("string", "CB-2026-999999", "It's C B 2026 814273.")
    assert value_in_quote("money", 248.5, "two hundred forty eight dollars and fifty cents")


# ----------------------------------------------------------------------------- samples, reference transcripts

def _ctx(tmp_path, transcriber):
    return make_ctx(tmp_path, **{"ocr.transcriber": transcriber})


@pytest.fixture(scope="module")
def reference_run(tmp_path_factory):
    ctx = _ctx(tmp_path_factory.mktemp("aud"), f"reference:{AUDIO / 'labels'}")
    return ctx, evaluate(ctx, AUDIO, run_pipeline=True)


def test_reference_transcripts_classify_and_never_leak(reference_run):
    ctx, report = reference_run
    assert report["documents"] == 4 and report["classification_accuracy"] == 1.0
    assert report["pii_leakage"] == 0
    envs = [json.loads(ctx.store.get_bytes(k)) for k in ctx.store.list("envelope/")]
    call = next(e for e in envs if e["file_name"] == "merchant_call.wav")
    g = ctx.get_model("guarded", GuardedDoc, doc_id=call["doc_id"])
    assert any(f.kind == "pan" for f in g.findings) and "4111" not in g.pages[0].text
    assert g.pages[0].text.startswith("[transcript of merchant_call.wav; engine: reference]")
    assert "spk_0:" in g.pages[0].text  # Transcribe-style speaker labels


def test_saved_claude_answers_replay_on_audio():
    from tests.conftest import make_ctx  # noqa: F401

    import os
    os.environ["UIF_TRANSCRIBER"] = f"reference:{AUDIO / 'labels'}"
    try:
        report = parity.replay_eval(ROOT / "evals" / "audio" / "answers" / "claude-code", AUDIO)
    finally:
        del os.environ["UIF_TRANSCRIBER"]
    assert report["unanswered_documents"] == 0, "transcripts drifted: regenerate requests and re-answer"
    assert gate(report) == [] and report["required_f1"] == 1.0


# ----------------------------------------------------------------------------- recognizers

def test_low_accuracy_transcripts_send_every_fact_to_review(tmp_path):
    class Garbled(fmt.Transcriber):
        name = "garbled"

        def available(self):
            return True

        def transcribe(self, data, file_name):
            return fmt.TranscriptResult("Case: RC-2026-0001. Merchant: Blue Harbor Coffee LLC. Analyst: X. "
                                        "Recommendation: monitor. Exposure estimate: $1,000.00. risk review",
                                        self.name, ["asr_low_accuracy"])

    ctx = make_ctx(tmp_path)
    ctx.providers.ocr = LocalOCR(transcriber=Garbled())
    from uif.runner import process_bytes

    run = process_bytes(ctx, b"RIFF fake", "memo.wav", "internal", "test")
    assert run.ok
    val = ctx.get_model("validated", Validated, doc_id=run.doc_id)
    assert val.facts and all(f.review_status == ReviewStatus.needs_review for f in val.facts)
    assert all("source:asr_low_accuracy" in f.review_reasons for f in val.facts)
    assert any(t.reason == "source_quality:asr_low_accuracy" for t in val.review_tasks)


def test_no_transcriber_halts_cleanly(tmp_path):
    ctx = make_ctx(tmp_path)
    none = fmt.ChainTranscriber([fmt.WhisperCppTranscriber(binary="/nonexistent", model="/nonexistent")])
    ctx.providers.ocr = LocalOCR(transcriber=none)
    from uif.runner import process_bytes

    last = process_bytes(ctx, b"RIFF fake", "memo.wav", "internal", "test").results[-1]
    assert last.step == "normalize" and last.halt and "no transcriber" in last.detail


@pytest.mark.skipif(not fmt.PocketSphinxTranscriber().available(), reason="pocketsphinx/ffmpeg not installed")
def test_real_recognition_with_pocketsphinx_is_flagged_and_reviewed(tmp_path):
    ctx = _ctx(tmp_path, "pocketsphinx")
    report = evaluate(ctx, AUDIO, run_pipeline=True)
    assert report["pii_leakage"] == 0
    for k in ctx.store.list("normalized") + ctx.store.list("restricted/normalized/"):
        assert "asr_low_accuracy" in NormalizedDoc.model_validate_json(ctx.store.get_bytes(k)).quality_flags
    auto = ctx.providers.warehouse.query("select count(*) from extracted_fact where review_status = 'auto_accepted'")
    assert auto[0][0] == 0  # nothing from a low-accuracy transcript is trusted


@pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("say"))
                    or not shutil.which("ffmpeg"), reason="no text-to-speech engine or ffmpeg")
def test_audio_generation(tmp_path):
    from uif.synth_audio import generate_audio

    summary = generate_audio(tmp_path / "audio")
    assert summary["documents"] == 4
    lab = json.loads((tmp_path / "audio" / "labels" / "merchant_call.wav.json").read_text())
    assert lab["reference_transcript"].startswith("spk_0:") and lab["raw_identifiers"] == ["4111111111111111"]


# ----------------------------------------------------------------------------- AWS Transcribe

def test_transcribe_adapter_stages_in_restricted_and_renders_speakers(monkeypatch):
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "t")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "t")
    from uif.providers.aws import S3Store, TranscribeTranscriber

    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="uif-audio-test")
        store = S3Store("uif-audio-test", "uif")

        class FakeTranscribe:
            def __init__(self):
                self.started = None

            def start_transcription_job(self, **kw):
                self.started = kw
                out_key = kw["OutputKey"].split("uif/", 1)[1]
                store.put_bytes(out_key, json.dumps({"results": {
                    "transcripts": [{"transcript": "ignored"}],
                    "audio_segments": [
                        {"speaker_label": "spk_0", "transcript": "Can I have the case number?"},
                        {"speaker_label": "spk_1", "transcript": "It's CB 2026 814273."},
                        {"speaker_label": "spk_1", "transcript": "This is Blue Harbor Coffee."}]}}).encode())

            def get_transcription_job(self, TranscriptionJobName):
                return {"TranscriptionJob": {"TranscriptionJobStatus": "COMPLETED"}}

        fake = FakeTranscribe()
        res = TranscribeTranscriber(store, client=fake, poll_s=0).transcribe(b"RIFF", "call.wav")
        assert res.text == "spk_0: Can I have the case number?\nspk_1: It's CB 2026 814273. This is Blue Harbor Coffee."
        assert fake.started["MediaFormat"] == "wav" and fake.started["Settings"]["ShowSpeakerLabels"]
        assert fake.started["Media"]["MediaFileUri"].startswith("s3://uif-audio-test/uif/restricted/asr-staging/")
        assert fake.started["OutputKey"].startswith("uif/restricted/asr-output/")
        assert all(k.startswith("restricted/") for k in store.list(""))
