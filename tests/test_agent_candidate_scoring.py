from backstage_agent.agent import BackstageAgent
from backstage_agent.candidate_models import CandidateFeatures, CandidateScore, ScoreBand
from backstage_agent.models import EmailMessage, ProjectNotice, ReviewDecision, ScreeningDecision
from backstage_agent.project_screener import project_to_notice
from datetime import date
import json


class FakeEmailClient:
    def fetch_messages(self, limit, days=1, target_date=None):
        return [EmailMessage("m1", "Backstage", "sender", None, "", "text")]


class FakeProjectPages:
    def fetch_html(self, url):
        return ""


class FakeFeatureExtractor:
    def extract(self, candidate):
        return CandidateFeatures(
            role_type="scripted_acting",
            project_type="theater",
            requirements={},
            project_signals={"career_goal_alignment": "high", "has_public_performance": True},
            compensation={"type": "paid", "amount_known": True},
            uncertainty={"compensation_missing": False, "role_details_sparse": False},
            evidence_snippets=["Evidence"],
        )


class FailingFeatureExtractor:
    def extract(self, candidate):
        raise RuntimeError(f"boom for {candidate.title}")


class FakeProjectScreener:
    def screen(self, notice):
        return ScreeningDecision(
            notice=project_to_notice(notice),
            score=0.9,
            should_apply=True,
            reasons=["project ok"],
            final_bucket="auto_apply_draft",
            classifier_json={"project_type": "theater"},
        )


class FakeReviewer:
    def review_project(self, notice, initial_bucket=None, classifier_json=None):
        return ReviewDecision(
            notice=notice,
            status="approved",
            score=0.9,
            reasons=["approved"],
            final_bucket=initial_bucket,
        )


def test_manual_scoring_scores_project_only_candidate_when_roles_missing(monkeypatch, settings_factory, tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)

    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Project With No Roles",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="project-with-no-roles",
            )
        ],
    )
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: [])

    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.project_screener = FakeProjectScreener()
    agent.reviewer = FakeReviewer()
    agent.feature_extractor = FakeFeatureExtractor()

    agent.scan(limit=1, target_date=date(2026, 7, 15))
    result = agent.score_candidates_for_date(date(2026, 7, 15))
    candidates = agent.store.search_candidates()

    assert result.candidates_scored == 1
    assert candidates[0]["candidate_type"] == "project_only"
    assert candidates[0]["overall_score"] > 0


def test_manual_scoring_persists_auditable_fallback_when_scoring_step_fails(
    monkeypatch,
    settings_factory,
    tmp_path,
):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)

    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Broken Candidate",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="broken-candidate",
            )
        ],
    )
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: [])

    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.project_screener = FakeProjectScreener()
    agent.reviewer = FakeReviewer()
    agent.feature_extractor = FailingFeatureExtractor()

    agent.scan(limit=1, target_date=date(2026, 7, 15))
    result = agent.score_candidates_for_date(date(2026, 7, 15))
    candidates = agent.store.search_candidates()
    features_payload = json.loads(candidates[0]["features_json"])
    score_payload = json.loads(candidates[0]["score_json"])

    assert result.candidates_scored == 1
    assert candidates[0]["overall_score"] == 0
    assert candidates[0]["draft_suggestion"] == 0
    assert features_payload["raw"]["fallback"]["stage"] == "feature_extraction"
    assert "RuntimeError" in features_payload["raw"]["fallback"]["error"]
    assert score_payload["score_trace"]["fallback"]["used"] is True
    assert score_payload["score_trace"]["fallback"]["stage"] == "feature_extraction"
    assert "Candidate scoring fallback used" in score_payload["negative_drivers"]


def test_manual_scoring_keeps_scores_attached_to_original_role_after_ranking(
    monkeypatch,
    settings_factory,
    tmp_path,
):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)

    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Ranked Project",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="ranked-project",
            )
        ],
    )

    roles = [
        _role_notice(
            title="Ranked Project - Ensemble",
            role="Ensemble",
            role_key="role-low-score",
        ),
        _role_notice(
            title="Ranked Project - Lead",
            role="Lead",
            role_key="role-high-score",
        ),
    ]
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: roles)

    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.project_pages.fetch_html = lambda url: "<html></html>"
    agent.project_screener = FakeProjectScreener()
    agent.reviewer = FakeReviewer()
    agent.reviewer.review_project = lambda notice, initial_bucket=None, classifier_json=None: ReviewDecision(
        notice=notice,
        status="hold",
        score=0.3,
        reasons=["project review"],
        final_bucket="ready_for_review",
    )

    def fake_score(candidate, project_decision=None, project_review=None):
        overall_score = 61 if candidate.role_key == "role-low-score" else 94
        return (
            CandidateFeatures(
                role_type="scripted_acting",
                project_type="theater",
                requirements={},
                project_signals={"career_goal_alignment": "high", "has_public_performance": True},
                compensation={"type": "paid", "amount_known": True},
                uncertainty={"compensation_missing": False, "role_details_sparse": False},
                evidence_snippets=[candidate.title],
                raw={"role_key": candidate.role_key},
            ),
            [],
            CandidateScore(
                overall_score=overall_score,
                score_band=ScoreBand.TOP_PRIORITY if overall_score >= 90 else ScoreBand.MAYBE_REVIEW,
                subscores={"their_requirements_match": overall_score},
                score_caps=[],
                positive_drivers=[candidate.role_key],
                negative_drivers=[],
                score_trace={"source_role_key": candidate.role_key},
                draft_suggestion=overall_score >= 90,
                scoring_version="test",
            ),
        )

    agent._score_candidate_with_fallback = fake_score

    agent.scan(limit=1, target_date=date(2026, 7, 15))
    result = agent.score_candidates_for_date(date(2026, 7, 15))
    candidates = agent.store.search_candidates()
    candidates_by_role = {row["role_key"]: row for row in candidates}

    assert result.candidates_scored == 2
    assert candidates_by_role["role-low-score"]["overall_score"] == 61
    assert candidates_by_role["role-low-score"]["rank_position"] == 2
    assert candidates_by_role["role-high-score"]["overall_score"] == 94
    assert candidates_by_role["role-high-score"]["rank_position"] == 1
    assert json.loads(candidates_by_role["role-low-score"]["score_json"])["score_trace"]["source_role_key"] == "role-low-score"
    assert json.loads(candidates_by_role["role-high-score"]["score_json"])["score_trace"]["source_role_key"] == "role-high-score"


def test_manual_scoring_ranks_candidates_globally_across_projects(
    monkeypatch,
    settings_factory,
    tmp_path,
):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)

    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Lower Project",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="lower-project",
            ),
            ProjectNotice(
                source_message_id="m1",
                title="Higher Project",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="higher-project",
            ),
        ],
    )

    def fake_roles(project, html):
        if project.project_key == "lower-project":
            return [
                _role_notice(
                    title="Lower Project - Role",
                    role="Supporting",
                    role_key="lower-role",
                    project="Lower Project",
                    project_key="lower-project",
                )
            ]
        return [
            _role_notice(
                title="Higher Project - Role",
                role="Lead",
                role_key="higher-role",
                project="Higher Project",
                project_key="higher-project",
            )
        ]

    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", fake_roles)

    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.project_pages.fetch_html = lambda url: "<html></html>"
    agent.project_screener = FakeProjectScreener()
    agent.reviewer = FakeReviewer()
    agent.reviewer.review_project = lambda notice, initial_bucket=None, classifier_json=None: ReviewDecision(
        notice=notice,
        status="hold",
        score=0.3,
        reasons=["project review"],
        final_bucket="ready_for_review",
    )

    def fake_score(candidate, project_decision=None, project_review=None):
        overall_score = 50 if candidate.role_key == "lower-role" else 95
        return (
            CandidateFeatures(
                role_type="scripted_acting",
                project_type="theater",
                requirements={},
                project_signals={},
                compensation={},
                uncertainty={},
                evidence_snippets=[candidate.title],
                raw={"role_key": candidate.role_key},
            ),
            [],
            CandidateScore(
                overall_score=overall_score,
                score_band=ScoreBand.TOP_PRIORITY if overall_score >= 90 else ScoreBand.LOW_PRIORITY,
                subscores={"their_requirements_match": overall_score},
                score_caps=[],
                positive_drivers=[candidate.role_key],
                negative_drivers=[],
                score_trace={"source_role_key": candidate.role_key},
                draft_suggestion=overall_score >= 90,
                scoring_version="test",
            ),
        )

    agent._score_candidate_with_fallback = fake_score

    agent.scan(limit=1, target_date=date(2026, 7, 15))
    agent.score_candidates_for_date(date(2026, 7, 15))
    candidates = agent.store.search_candidates()

    assert [row["role_key"] for row in candidates] == ["higher-role", "lower-role"]
    assert [row["rank_position"] for row in candidates] == [1, 2]


def test_manual_scoring_skips_existing_by_default_and_overwrites_explicitly(
    monkeypatch,
    settings_factory,
    tmp_path,
):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)
    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Manual Project",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="manual-project",
            )
        ],
    )
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: [])
    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.project_screener = FakeProjectScreener()
    agent.reviewer = FakeReviewer()
    agent.feature_extractor = FakeFeatureExtractor()
    agent.scan(limit=1, target_date=date(2026, 7, 15))

    first = agent.score_candidates_for_date(date(2026, 7, 15))
    safe_repeat = agent.score_candidates_for_date(date(2026, 7, 15))
    overwrite = agent.score_candidates_for_date(date(2026, 7, 15), overwrite=True)

    assert first.candidates_scored == 1
    assert safe_repeat.candidates_scored == 0
    assert safe_repeat.candidates_skipped_existing == 1
    assert safe_repeat.candidates_deleted == 0
    assert overwrite.candidates_scored == 1
    assert overwrite.candidates_skipped_existing == 0
    assert overwrite.candidates_deleted == 1


def _role_notice(
    title: str,
    role: str,
    role_key: str,
    project: str = "Ranked Project",
    project_key: str = "ranked-project",
):
    from backstage_agent.models import CastingNotice

    return CastingNotice(
        source_message_id="m1",
        title=title,
        project=project,
        role=role,
        location="Los Angeles",
        compensation="$100",
        role_key=role_key,
        description=f"{role} role",
        application_url="https://example.com/apply",
        raw_text=f"{role} role",
        project_key=project_key,
    )
