"""Domain errors for agent configuration and routing decisions."""


class AgentNotFoundError(Exception):
    pass


class AgentConflictError(Exception):
    pass


class RoutingAmbiguityError(Exception):
    pass


class RoutingNoMatchError(Exception):
    pass
