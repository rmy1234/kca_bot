from app.rag import pack_context


def test_pack_context_keeps_order_and_truncates_the_chunk_crossing_the_budget():
    chunks = ["a" * 500, "b" * 500, "c" * 500]
    assert pack_context(chunks, 1200) == ["a" * 500, "b" * 500, "c" * 200]


def test_pack_context_skips_fragments_too_short_to_be_useful():
    assert pack_context(["a" * 500, "b" * 500], 600) == ["a" * 500]


def test_pack_context_truncates_a_single_long_chunk():
    assert pack_context(["x" * 1000], 300) == ["x" * 300]


def test_pack_context_without_material_is_empty():
    assert pack_context([], 4000) == []
