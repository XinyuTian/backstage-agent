from backstage_agent.ui import (
    _get_route,
    _post_route,
    _record_candidate_feedback_from_params,
    _render_candidates_index,
)


class FakeStore:
    def search_candidates(self, query="", band="all", limit=200):
        self.query = query
        self.band = band
        self.limit = limit
        return [
            {
                "id": 1,
                "title": "Play - Lead",
                "overall_score": 86,
                "score_band": "strong_candidate",
                "rank_position": 1,
                "draft_suggestion": 1,
                "score_json": (
                    '{"positive_drivers":["Explicit role fit"],'
                    '"negative_drivers":["Compensation unknown"],'
                    '"subscores":{"their_requirements_match":30}}'
                ),
                "features_json": '{"role_type":"scripted_acting"}',
                "requirement_match_json": "[]",
            }
        ]


def test_candidate_routes_exclude_legacy_dashboard_actions():
    assert _get_route("/") == ("redirect", "/candidates")
    assert _get_route("/candidates") == ("candidates", None)
    assert _post_route("/candidate-feedback") == "candidate_feedback"
    assert _post_route("/cover-letter") is None


def test_render_candidates_index_shows_ranked_score_and_feedback_form():
    store = FakeStore()

    html = _render_candidates_index(store, {"q": ["Lead"], "band": ["strong_candidate"]})

    assert "Backstage Candidates" in html
    assert "Play - Lead" in html
    assert "86" in html
    assert "strong_candidate" in html
    assert "Explicit role fit" in html
    assert "Compensation unknown" in html
    assert 'action="/candidate-feedback"' in html
    assert 'type="submit"' in html
    assert "Human score" in html
    assert store.query == "Lead"
    assert store.band == "strong_candidate"


def test_render_candidates_index_handles_empty_results():
    class EmptyStore:
        def search_candidates(self, query="", band="all", limit=200):
            return []

    html = _render_candidates_index(EmptyStore(), {})

    assert "No candidates match the current filters." in html


def test_record_candidate_feedback_from_params_uses_persisted_agent_score():
    class FeedbackStore(FakeStore):
        def record_candidate_feedback(self, feedback):
            self.feedback = feedback
            return 9

    store = FeedbackStore()

    feedback_id = _record_candidate_feedback_from_params(
        store,
        {
            "candidate_id": ["1"],
            "human_score": ["45"],
            "affected_components": ["identity_match"],
            "failure_modes": ["overweighted_signal"],
            "reason": ["Nationality over-weighted."],
        },
    )

    assert feedback_id == 9
    assert store.feedback.agent_score == 86
    assert store.feedback.human_score == 45
    assert store.feedback.affected_components == ["identity_match"]
    assert store.feedback.failure_modes == ["overweighted_signal"]
