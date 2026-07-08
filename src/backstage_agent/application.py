from __future__ import annotations

from .models import ActorProfile, ApplicationDraft, ScreeningDecision


class ApplicationService:
    def __init__(self, profile: ActorProfile, dry_run: bool):
        self.profile = profile
        self.dry_run = dry_run

    def create_or_submit(self, decision: ScreeningDecision) -> ApplicationDraft:
        cover_note = self._cover_note(decision)
        status = "drafted"
        blocker_reason = ""
        if not self.dry_run:
            status = "blocked_no_live_adapter"
            blocker_reason = (
                "Automatic Backstage submission is not available in the current "
                "local runner. Submit manually or use an approved interactive browser session."
            )
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=cover_note,
            dry_run=self.dry_run,
            status=status,
            blocker_reason=blocker_reason,
        )

    def failed_attempt(self, decision: ScreeningDecision, reason: str) -> ApplicationDraft:
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=self._cover_note(decision),
            dry_run=self.dry_run,
            status="failed_application_attempt",
            blocker_reason=reason,
        )

    def _cover_note(self, decision: ScreeningDecision) -> str:
        return self.profile.cover_note_template.format(
            actor_name=self.profile.name,
            role=decision.notice.role or decision.notice.title,
            project=decision.notice.project or "your project",
        )
