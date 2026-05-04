"""Messages service — store, paginate, and mark delivered."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, User
from app.schemas import ConversationSummary, MessageResponse, SendMessageRequest


async def store_message(
    sender_id: UUID,
    data: SendMessageRequest,
    db: AsyncSession,
) -> MessageResponse:
    """Persist an encrypted message to the database.

    Called either by the REST fallback (POST /messages) or by the WebSocket
    handler before attempting live delivery.

    Args:
        sender_id: UUID of the authenticated sender.
        data: Validated message payload including recipient and encrypted blob.
        db: Active database session.

    Returns:
        The persisted message record.

    Raises:
        HTTPException: 404 if the recipient does not exist.
        HTTPException: 400 if the sender tries to message themselves.
    """
    if sender_id == data.to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send a message to yourself",
        )

    result = await db.execute(
        select(User).where(User.id == data.to, User.deleted_at.is_(None))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recipient not found",
        )

    payload_dict = data.payload.model_dump(by_alias=True)
    msg = Message(
        from_user_id=sender_id,
        to_user_id=data.to,
        payload=payload_dict,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return MessageResponse.model_validate(msg)


async def mark_delivered(message_id: UUID, db: AsyncSession) -> None:
    """Mark a message as delivered after successful WebSocket push.

    Args:
        message_id: UUID of the message to update.
        db: Active database session.
    """
    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if msg:
        msg.delivered = True
        await db.commit()


async def get_undelivered(recipient_id: UUID, db: AsyncSession) -> list[Message]:
    """Return all undelivered messages for *recipient_id*, oldest first.

    Called on WebSocket reconnect to flush the offline queue.

    Args:
        recipient_id: UUID of the reconnecting user.
        db: Active database session.

    Returns:
        Ordered list of undelivered Message ORM objects.
    """
    result = await db.execute(
        select(Message)
        .where(
            Message.to_user_id == recipient_id,
            Message.delivered.is_(False),
            Message.deleted_at.is_(None),
        )
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def list_conversations(user_id: UUID, db: AsyncSession) -> list[ConversationSummary]:
    """Return a summary of all conversations the user participates in.

    Each entry represents the most recent message exchanged with another user,
    sorted by most-recent first.

    Args:
        user_id: UUID of the authenticated user.
        db: Active database session.

    Returns:
        List of ConversationSummary objects, one per conversation partner.
    """
    # Find the latest message timestamp for each conversation partner.
    subq = (
        select(
            case(
                (Message.from_user_id > Message.to_user_id, Message.from_user_id),
                else_=Message.to_user_id,
            ).label("user_a"),
            case(
                (Message.from_user_id < Message.to_user_id, Message.from_user_id),
                else_=Message.to_user_id,
            ).label("user_b"),
            func.max(Message.created_at).label("last_ts"),
        )
        .where(
            or_(Message.from_user_id == user_id, Message.to_user_id == user_id),
            Message.deleted_at.is_(None),
        )
        .group_by("user_a", "user_b")
        .subquery()
    )

    result = await db.execute(
        select(subq, User)
        .join(
            User,
            or_(
                (subq.c.user_a != str(user_id)) & (User.id == subq.c.user_a),
                (subq.c.user_b != str(user_id)) & (User.id == subq.c.user_b),
            ),
        )
        .order_by(subq.c.last_ts.desc())
    )
    rows = result.all()

    summaries = []
    for row in rows:
        last_ts = row.last_ts
        if isinstance(last_ts, str):
            last_ts = datetime.fromisoformat(last_ts)
        if last_ts and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)
        summaries.append(
            ConversationSummary(
                user_id=row.User.id,
                display_name=row.User.display_name,
                username=row.User.username,
                last_message_at=last_ts,
            )
        )
    return summaries


async def get_conversation_messages(
    user_id: UUID,
    partner_id: UUID,
    limit: int,
    before: str | None,
    db: AsyncSession,
) -> list[MessageResponse]:
    """Return paginated message history between two users.

    Messages are returned newest-first. Use the ``before`` cursor (ISO-8601
    timestamp of the oldest message in the previous page) to paginate backwards.

    Args:
        user_id: UUID of the authenticated user.
        partner_id: UUID of the conversation partner.
        limit: Maximum number of messages to return (1–100).
        before: ISO-8601 timestamp; only return messages created before this.
        db: Active database session.

    Returns:
        List of MessageResponse objects, newest first.

    Raises:
        HTTPException: 404 if the partner does not exist.
    """
    result = await db.execute(
        select(User).where(User.id == partner_id, User.deleted_at.is_(None))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    stmt = (
        select(Message)
        .where(
            or_(
                (Message.from_user_id == user_id) & (Message.to_user_id == partner_id),
                (Message.from_user_id == partner_id) & (Message.to_user_id == user_id),
            ),
            Message.deleted_at.is_(None),
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )

    if before:
        before_dt = datetime.fromisoformat(before)
        stmt = stmt.where(Message.created_at < before_dt)

    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [MessageResponse.model_validate(m) for m in messages]
