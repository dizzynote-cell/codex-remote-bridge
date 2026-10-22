"""Route input from fresh RPC state, never from a cached running badge."""
from turn_state import status


def running_turn(thread):
    turns = thread.get('turns') or []
    latest = turns[-1] if turns else None
    if latest and status(latest) in {'inProgress', 'in_progress', 'running'}:
        return latest.get('id')
    return None


def reconcile(active, thread):
    tid = thread.get('id')
    if not tid:
        return
    current = running_turn(thread)
    if current:
        active[tid] = current
    else:
        active.pop(tid, None)


def release_owned(active, thread_id, turn_id):
    if turn_id and active.get(thread_id) == turn_id:
        active.pop(thread_id, None)


def steer_or_idle(thread_id, inputs, read, call):
    """Return steered turn ID, or None for a freshly confirmed idle thread.

    Only the explicit 'no active turn' rejection is safe to recover from.
    Transport failures may have delivered the message and must not be resent.
    The caller holds the bridge's reentrant RPC lock throughout this operation.
    """
    for attempt in range(2):
        snapshot = read(thread_id)
        current = running_turn(snapshot)
        if not current:
            turns = snapshot.get('turns') or []
            if turns and status(turns[-1]) not in {'completed', 'failed', 'interrupted', 'cancelled'}:
                raise RuntimeError('无法确认当前回合状态，请稍后重试')
            return None
        try:
            call('turn/steer', {'threadId': thread_id, 'expectedTurnId': current, 'input': inputs})
            return current
        except RuntimeError as error:
            if 'no active turn to steer' not in str(error).lower():
                raise
            if attempt:
                raise RuntimeError('回合状态正在变化，请稍后重试；本次消息未追加') from error
    return None
