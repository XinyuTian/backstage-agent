from __future__ import annotations

from .models import ActorProfile, ApplicationDraft, ScreeningDecision


class ApplicationService:
    def __init__(self, profile: ActorProfile, dry_run: bool):
        self.profile = profile
        self.dry_run = dry_run

    def create_or_submit(self, decision: ScreeningDecision) -> ApplicationDraft:
        cover_note = self._cover_note(decision)
        status = "drafted"
        if not self.dry_run:
            status = "blocked_no_live_adapter"
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=cover_note,
            dry_run=self.dry_run,
            status=status,
        )

    def _cover_note(self, decision: ScreeningDecision) -> str:
        return self.profile.cover_note_template.format(
            actor_name=self.profile.name,
            role=decision.notice.role or decision.notice.title,
            project=decision.notice.project or "your project",
        )
