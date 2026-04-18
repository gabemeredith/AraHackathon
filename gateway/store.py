"""In-memory session store for the gateway.

Single-process. Lives only as long as the gateway. See CLAUDE.md session schema.
"""

import secrets
import threading


class Store:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._handle_index: dict[str, str] = {}
        self._lock = threading.Lock()

    def create_session(
        self,
        initiator: dict,
        participants: list[dict],
        duration_min: int,
        window: dict,
    ) -> str:
        session_id = f"sess_{secrets.token_hex(4)}"
        session = {
            "session_id": session_id,
            "initiator": initiator,
            "participants": [
                {
                    "handle": p["handle"],
                    "name": p.get("name", ""),
                    "status": p.get("status", "pending"),
                    "freebusy": [],
                    "declared": None,
                }
                for p in participants
            ],
            "duration_min": duration_min,
            "window": window,
            "inbound": [],
            "proposed_time": None,
            "confirmed": False,
            "seen_handles": [],
        }
        with self._lock:
            self._sessions[session_id] = session
            for p in participants:
                self._handle_index[p["handle"]] = session_id
            if initiator.get("handle"):
                self._handle_index[initiator["handle"]] = session_id
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def session_id_for_handle(self, phone: str) -> str | None:
        return self._handle_index.get(phone)

    def append_inbound(
        self,
        session_id: str,
        message_handle: str,
        from_: str,
        body: str,
        ts: str,
    ) -> bool:
        """Append an inbound message. Returns False if message_handle was already seen."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if message_handle in session["seen_handles"]:
                return False
            session["seen_handles"].append(message_handle)
            session["inbound"].append(
                {
                    "message_handle": message_handle,
                    "from": from_,
                    "body": body,
                    "ts": ts,
                }
            )
            return True


store = Store()
