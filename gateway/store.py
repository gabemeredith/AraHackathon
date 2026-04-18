"""Shared store client. Upstash Redis (REST) is the default target.

Session schema (see CLAUDE.md):
  {session_id, initiator, participants, duration_min, window,
   inbound, proposed_time, confirmed}

Sessions are keyed by `session:{session_id}`.
A phone-number -> session_id index lets the /sms webhook route replies:
  `participant:{number}` -> session_id
"""


class Store:
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token

    def get_session(self, session_id: str) -> dict | None:
        raise NotImplementedError

    def put_session(self, session_id: str, session: dict) -> None:
        raise NotImplementedError

    def append_inbound(self, session_id: str, msg: dict) -> None:
        """Append {from, body, ts} to session.inbound atomically if possible."""
        raise NotImplementedError

    def session_id_for_number(self, number: str) -> str | None:
        raise NotImplementedError

    def bind_number(self, number: str, session_id: str) -> None:
        raise NotImplementedError
