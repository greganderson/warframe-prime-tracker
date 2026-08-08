from app.public_export import normalize_relics


def test_public_export_collapses_refinements():
    reward = [{"rewardName":f"/Lotus/Item{i}","rarity":"COMMON"} for i in range(6)]
    entries = []
    for number in range(1, 101):
        for refinement in range(4):
            entries.append({"name":f"Lith A{number} Relic","relicRewards":reward,"refinement":refinement})
    normalized = normalize_relics({"ExportRelicArcane":entries})
    assert len(normalized) == 100
    assert normalized[0]["id"] == "lith-a1"
