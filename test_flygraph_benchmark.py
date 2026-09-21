import flygraph_benchmark as f


def sample_task():
    return {
        "id": "T",
        "category": "test",
        "question": "Which symbol appears most often across the six source slots?",
        "slot_options": ["RED", "BLUE", "GREEN"],
        "slot_values": ["RED", "BLUE", "BLUE", "GREEN", "BLUE", "RED"],
        "answer_options": {
            "RED": "RED is the answer.",
            "BLUE": "BLUE is the answer.",
            "GREEN": "GREEN is the answer."
        },
        "expected": "BLUE"
    }


def test_graph_hash_is_frozen():
    assert f.sha256(f.GRAPH_PATH) == f.GRAPH_SHA256


def test_dynamic_packet_has_six_slots():
    q = f.make_questions(sample_task())
    assert all(f"slot_{i}" in q for i in range(1, 7))
    assert "answer" in q
    assert "decision_ready" in q


def test_answer_has_unknown_escape():
    q = f.make_questions(sample_task())
    assert "UNKNOWN" in q["answer"]["criteria"]


def test_slot_options_have_unknown():
    q = f.make_questions(sample_task())
    assert "UNKNOWN" in q["slot_1"]["criteria"]
