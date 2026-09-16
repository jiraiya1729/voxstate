"""Domain errors for durable case operations."""


class CaseNotFoundError(Exception):
    pass


class CaseConcurrencyError(Exception):
    pass


class CaseAttachmentError(Exception):
    pass
