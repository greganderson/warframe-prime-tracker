import wave
from pathlib import Path

import pytest

from app import voice

RELICS = [{"id":f"{era.lower()}-{code.lower()}","era":era,"code":code} for era,code in [
    ("Lith","B4"),("Lith","D4"),("Lith","T5"),("Lith","G11"),("Meso","C2"),("Meso","N17"),
    ("Neo","Z10"),("Axi","A12"),("Axi","S12"),("Axi","V9"),("Axi","L4")]]


def ids(results): return [result["relic_id"] for result in results]


def test_parses_eras_letters_and_numbers():
    assert ids(voice.parse("lit bee four mezzo see two neo zee ten axe vee nine",RELICS)) == \
        ["lith-b4","meso-c2","neo-z10","axi-v9"]


def test_compound_numbers_and_phonetic_alphabet():
    assert ids(voice.parse("mezzo november seventeen lift golf eleven",RELICS)) == ["meso-n17","lith-g11"]


def test_mission_era_is_used_when_no_era_is_spoken():
    assert ids(voice.parse("tee five golf eleven",RELICS,"Lith")) == ["lith-t5","lith-g11"]
    assert voice.parse("tee five",RELICS,"Omni")[0]["relic_id"] == "lith-t5"


def test_misheard_letter_falls_back_to_the_only_similar_relic():
    assert ids(voice.parse("mezzo bee two",RELICS)) == ["meso-c2"]


def test_ambiguous_letter_offers_options():
    result = voice.parse("lit e four",RELICS)[0]
    assert result["relic_id"] is None and result["options"] == ["lith-b4","lith-d4"]


def test_letter_swallowed_by_era_word_offers_likely_relics():
    result = voice.parse("axes twelve",RELICS)[0]
    assert result["heard"] == "Axi ?12" and result["options"] == ["axi-a12","axi-s12"]
    assert ids(voice.parse("axle four",RELICS)) == ["axi-l4"]


def test_unknown_relic_keeps_its_slot():
    assert voice.parse("neo bee one lit bee four",RELICS) == [
        {"heard":"Neo B1","relic_id":None,"options":[]},
        {"heard":"Lith B4","relic_id":"lith-b4","options":[]}]


def test_voice_socket_transcribes_speech(client):
    if not voice.available(): pytest.skip("Vosk model not installed")
    with wave.open(str(Path(__file__).parent/"fixtures"/"lith-b4-meso-b1.wav")) as clip:
        rate, audio = clip.getframerate(), clip.readframes(clip.getnframes())
    with client.websocket_connect(f"/api/v1/voice?rate={rate}") as socket:
        for start in range(0,len(audio),8000): socket.send_bytes(audio[start:start+8000])
        socket.send_text("stop")
        while not (message:=socket.receive_json()).get("done"): pass
    assert ids(message["relics"]) == ["lith-b4","meso-b1"]


def test_voice_status(client):
    assert client.get("/api/v1/voice/status").json() == {"available":voice.available()}
