class Reject(Exception):
    """The request is invalid. The app marks the item failed and shows the message."""


class Conflict(Exception):
    """The request clashes with existing data and needs a human decision."""


class Duplicate(Exception):
    """The same entity was already stored (a safe retry): carries the id that exists."""

    def __init__(self, server_id: str):
        super().__init__(server_id)
        self.server_id = server_id
