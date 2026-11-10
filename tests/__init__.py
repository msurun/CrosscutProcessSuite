"""Shared settings for repository tests.

Keep CI timing allowances consistent across test suites.
"""

# Seconds allowed for OPC UA startup under coverage on slow CI workers.
OPCUA_SERVER_START_TIMEOUT_S = 30.0
