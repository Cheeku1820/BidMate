"""One row per turn of a project's conversation thread.

Not routed through app.takeoff.actions.commit(): a message is not a
takeoff mutation, must not appear in the undo stack, and changes nothing
there is to audit (docs/specs/conversation-panel.md, "Writes"). One
thread per project today; shared-vs-per-user is an open decision in
CLAUDE.md and becomes a column here when made, not a rewrite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The product's words, never user / assistant -- a wire field is one copy
# change away from being rendered.
ROLES = ("estimator", "answer")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint("role in ('estimator', 'answer')", name="ck_conversation_messages_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    # The screen descriptor the question was asked from; null on answers.
    screen: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
