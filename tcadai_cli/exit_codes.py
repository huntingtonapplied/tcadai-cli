"""Standard exit codes for the TCAD AI CLI.

These allow scripts and CI pipelines to distinguish between failure types.
"""

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_AUTH = 2
EXIT_NOT_FOUND = 3
EXIT_VALIDATION = 4
EXIT_NETWORK = 5
EXIT_SERVER = 6
EXIT_DUPLICATE = 7
EXIT_RUN_FAILED = 8  # `simulations wait`: the run ended failed/cancelled/stopped
EXIT_TIMEOUT = 9  # `simulations wait`: --timeout elapsed before a terminal state
EXIT_SIGINT = 130
EXIT_SIGTERM = 143
