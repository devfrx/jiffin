"""The harness's own failure: a message for whoever runs it, and no traceback."""


class HarnessError(Exception):
    pass
