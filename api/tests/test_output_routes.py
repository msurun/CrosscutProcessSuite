"""Validate output confirmation HTTP contracts without exposing a plant write API.

Route permissions and signed gateway envelopes remain separate enforcement layers.
"""

import pytest
from crosscut_api.gateway_routes import build_gateway_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class Mailbox:
    """Capture commands that the HTTP layer sends to the gateway process."""

    def __init__(self) -> None:
        """Start with no captured confirmation."""
        self.arguments = {}

    def start_output(self, arguments, actor):
        """Capture the authenticated human and bounded request."""
        self.arguments = arguments
        return {"accepted": True, "reason_code": "out_step_started"}

    def cancel_output(self, target, actor):
        """Report only the restoration state returned by the gateway."""
        return {"reason_code": "restored"}


@pytest.fixture
def mailbox_client():
    """Build isolated routes using the existing local-development actor dependency."""
    mailbox = Mailbox()
    app = FastAPI()
    app.include_router(build_gateway_router(lambda: mailbox))
    return mailbox, TestClient(app)


def test_confirmation_sends_a_new_test_identity_and_signed_amplitude(mailbox_client):
    """The gateway receives a signed increment, never an absolute output baseline."""
    mailbox, client = mailbox_client
    response = client.post("/gateway/output-tests", json={
        "target": "FIC.OUT", "amplitude": -1, "duration_s": 5,
    })
    assert response.json()["reason_code"] == "out_step_started"
    assert mailbox.arguments["amplitude"] == -1
    assert len(mailbox.arguments["test_id"]) == 32


@pytest.mark.parametrize("amplitude", [True, "1", None])
def test_confirmation_rejects_nonnumeric_amplitude_before_mailbox(mailbox_client, amplitude):
    """Boolean and coerced text values cannot become plant output increments."""
    mailbox, client = mailbox_client
    response = client.post("/gateway/output-tests", json={
        "target": "FIC.OUT", "amplitude": amplitude, "duration_s": 5,
    })
    assert response.status_code == 422
    assert mailbox.arguments == {}


def test_cancel_returns_the_gateway_restoration_result(mailbox_client):
    """The browser can distinguish verified return from an attempted return."""
    _, client = mailbox_client
    response = client.post("/gateway/output-tests/FIC.OUT/cancel")
    assert response.json() == {"reason_code": "restored"}
