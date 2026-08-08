import lzma

from app.public_export import (_decode_legacy_lzma_raw, decode_export_index,
                               normalize_relics, parse_farmable_relics)


def test_public_export_collapses_refinements():
    reward = [{"rewardName":f"/Lotus/Item{i}","rarity":"COMMON"} for i in range(6)]
    entries = []
    for number in range(1, 101):
        for refinement in range(4):
            entries.append({"name":f"Lith A{number} Relic","relicRewards":reward,"refinement":refinement})
    normalized = normalize_relics({"ExportRelicArcane":entries})
    assert len(normalized) == 100
    assert normalized[0]["id"] == "lith-a1"


def test_export_index_accepts_lzma_and_predecoded_cdn_content():
    index = "ExportRelicArcane_en.json!00_example\n"
    assert decode_export_index(lzma.compress(index.encode(), format=lzma.FORMAT_ALONE)) == index
    assert decode_export_index(index.encode()) == index
    assert decode_export_index(b"\xef\xbb\xbf" + index.encode()) == index


def test_windows_legacy_lzma_fallback_handles_declared_size_header():
    index = b"ExportRelicArcane_en.json!00_example\n"
    compressed = bytearray(lzma.compress(index, format=lzma.FORMAT_ALONE))
    compressed[5:13] = len(index).to_bytes(8, "little")
    assert _decode_legacy_lzma_raw(bytes(compressed)) == index


def test_farmable_relics_exclude_historical_relic_reward_archive():
    current = " ".join(f"Lith A{number} Relic" for number in range(1, 21))
    html = (
        f'<h3 id="missionRewards">{current}'
        '<h3 id="relicRewards">Axi Z99 Relic'
        '<h3 id="cetusRewards">Meso B1 Relic<h3 id="modByAvatar">'
        '<h3 id="relicByAvatar">Neo C2 Relic</body>'
    )
    farmable = parse_farmable_relics(html)
    assert "lith-a1" in farmable
    assert "meso-b1" in farmable
    assert "neo-c2" in farmable
    assert "axi-z99" not in farmable
