from counterside_mcp.stats import (
    NKM_STAT_TYPE,
    asset_type_for,
    humanize,
    normalize_relation_value,
    stat_type_value,
    tokenize,
)


def test_stat_enum_loaded():
    assert NKM_STAT_TYPE["NST_HP"] == 0
    assert NKM_STAT_TYPE["NST_ATK"] == 1
    assert len(NKM_STAT_TYPE) == 100


def test_stat_type_value_passthrough_and_lookup():
    assert stat_type_value(7) == 7
    assert stat_type_value("7") == 7
    assert stat_type_value("NST_ATK") == 1
    assert stat_type_value("NST_UNKNOWN") == 0
    assert stat_type_value(None) == 0
    assert stat_type_value("") == 0


def test_stat_type_value_truncates_floats():
    assert stat_type_value(7.9) == 7
    assert stat_type_value(-1.2) == -1


def test_asset_type_for():
    assert asset_type_for("a/b.png", ".png") == "Image"
    assert asset_type_for("a/b.wav", ".wav") == "Audio"
    assert asset_type_for("b/x.skel", ".skel") == "Spine skeleton"
    assert asset_type_for("b/x.atlas", ".atlas") == "Spine atlas"
    assert asset_type_for("b/x.bytes", ".bytes") == "TextAsset bytes"
    assert asset_type_for("b/TypeTree/Sprite/x", "") == "Unity Sprite"
    assert asset_type_for("b/SpriteMeta/x", "") == "Unity Sprite metadata"
    assert asset_type_for("b/Texture2D/x", "") == "Texture2D"
    assert asset_type_for("b/ObjectIndex/o.json", ".json") == "Unity object index"
    assert asset_type_for("b/x.abc", ".abc") == "ABC"


def test_asset_type_for_is_case_insensitive_on_extension():
    assert asset_type_for("a/b.PNG", ".PNG") == "Image"


def test_humanize():
    assert humanize("NST_HP_REGEN_RATE") == "Hp Regen Rate"


def test_normalize_relation_value_strips_punctuation():
    assert normalize_relation_value("AB_INVEN_ICON_NKM-X.png") == "abinveniconnkmxpng"


def test_tokenize_drops_one_char_terms():
    assert tokenize("unit respawn cost") == ["unit", "respawn", "cost"]
    assert tokenize("a bc") == ["bc"]
