"""Tests for shared segment labeling and transcript flattening."""

from call_center_api.segmentation import extract_segments, flatten_transcript, flatten_transcript_dicts


def test_extract_segments_labels_speakers():
    diarized = {
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "Thank you for calling billing support."},
            {"speaker": "SPEAKER_01", "start": 1.0, "end": 2.0, "text": "I'm calling about a charge on my account."},
        ]
    }
    labeled = extract_segments(diarized)
    assert len(labeled) == 2
    assert labeled[0].speaker == "AGENT"
    assert labeled[1].speaker == "CUSTOMER"


def test_flatten_transcript_includes_timestamps():
    diarized = {
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.5, "text": "Hello there."},
        ]
    }
    labeled = extract_segments(diarized)
    text = flatten_transcript(labeled)
    assert "[0.0s-1.5s] AGENT: Hello there." in text


def test_flatten_transcript_dicts_matches_labeled():
    diarized = {
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "Thank you for calling."},
        ]
    }
    labeled = extract_segments(diarized)
    dicts = [{"speaker": s.speaker, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text} for s in labeled]
    assert flatten_transcript(labeled) == flatten_transcript_dicts(dicts)


def test_extract_segments_empty_input():
    assert extract_segments(None) == []
    assert extract_segments({}) == []
