import lzma

from app.public_export import decode_export_index, normalize_relics


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
