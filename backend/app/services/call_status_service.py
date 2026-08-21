"""Was this call actually answered by a person?

One definition, used everywhere, because there were three and they
disagreed.

The naive rule -- inbound with zero duration -- is wrong for Ratha's setup.
`Call.duration_seconds` is populated from Vobiz's `RecordingDuration`
(adapters/ivr/vobiz.py), i.e. how long the *recording* ran, not how long a
human talked. A caller who reaches voicemail and leaves a 53-second message
produces duration=53 and reads as "answered", while the transcript plainly
shows the IVR's own "this person is not available" greeting. That exact
call was sitting in the Incoming list instead of Missed.

`agent_id` is not usable as a signal either: it is NULL on every one of the
585 calls in production -- the IVR ingest path never sets it.

So the ordering below leans on disposition, which is the only field that
reflects what actually happened on the call, and falls back to duration
only when nothing better exists.
"""

from __future__ import annotations

from typing import Optional

# Dispositions that mean nobody picked up.
NOT_ANSWERED = {"no_answer", "voicemail"}

# Dispositions that only exist because a real conversation took place --
# somebody quoted, booked, lost or agreed a callback.
ANSWERED = {"hot", "quoted", "booked", "lost", "callback"}


def _disp(value) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value)).strip().lower() or None


def is_missed_call(call) -> bool:
    """True when an inbound call was not answered by a person.

    Outbound calls are never "missed" from our side.
    """
    direction = str(getattr(getattr(call, "direction", None), "value", getattr(call, "direction", ""))).lower()
    if direction != "inbound":
        return False

    # A human's own classification always wins.
    human = _disp(getattr(call, "human_disposition", None))
    if human in NOT_ANSWERED:
        return True
    if human in ANSWERED:
        return False

    ai = _disp(getattr(call, "ai_disposition", None))
    if ai in NOT_ANSWERED:
        return True
    if ai in ANSWERED:
        return False

    # No disposition -- true for 311 of 585 production calls, because the
    # classify/judge chain has not run on them. Fall back to duration, which
    # is right for the common zero-length case and wrong only for
    # un-analysed voicemails, which cannot be distinguished without either a
    # disposition or a DialStatus from the provider.
    return (getattr(call, "duration_seconds", 0) or 0) == 0


def is_answered_call(call) -> bool:
    direction = str(getattr(getattr(call, "direction", None), "value", getattr(call, "direction", ""))).lower()
    if direction != "inbound":
        return False
    return not is_missed_call(call)


def missed_call_sql_filter():
    """SQLAlchemy predicate mirroring is_missed_call(), for count queries.

    Kept next to the Python version so the two cannot drift; any change here
    needs the same change above.
    """
    from sqlalchemy import and_, func, or_
    from app.models.call import Call, CallDirection

    def _lower(col):
        return func.lower(func.coalesce(col, ""))

    human = _lower(Call.human_disposition)
    ai = _lower(Call.ai_disposition)

    return and_(
        Call.direction == CallDirection.INBOUND,
        or_(
            human.in_(NOT_ANSWERED),
            and_(
                ~human.in_(ANSWERED),
                or_(
                    ai.in_(NOT_ANSWERED),
                    and_(
                        ~ai.in_(ANSWERED),
                        or_(Call.duration_seconds.is_(None), Call.duration_seconds == 0),
                    ),
                ),
            ),
        ),
    )
