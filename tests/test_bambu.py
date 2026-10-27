"""Sign-in with the Bambu Lab cloud against a recorded-style fake."""

import json

import pytest
from spoolsync.bambu import Bambu, BambuError, to_spool


class FakeHttp:
    def __init__(self, answers):
        self.answers = answers  # path -> list of (status, body)
        self.calls = []

    async def request(self, method, url, *, json_body=None, params=None, headers=None):
        path = url.split(".com", 1)[1]
        self.calls.append((method, path, json_body))
        status, body = self.answers[path].pop(0)
        return status, json.dumps(body), {}

    async def close(self):
        pass


LOGIN = "/v1/user-service/user/login"
SEND = "/v1/user-service/user/sendemail/code"


async def test_code_login_requests_the_mail(tmp_path):
    http = FakeHttp({LOGIN: [(200, {"loginType": "verifyCode"}), (200, {"accessToken": "T"})],
                     SEND: [(200, {})]})
    bambu = Bambu(tmp_path / "bambu.json", http)
    assert await bambu.login("a@b.de", "pw") == "code"
    assert ("POST", SEND, {"email": "a@b.de", "type": "codeLogin"}) in http.calls
    assert await bambu.submit_code(" 123456 ") == "ok"
    assert http.calls[-1][2] == {"account": "a@b.de", "code": "123456"}
    assert Bambu(tmp_path / "bambu.json", http).token == "T"  # kept across restarts


async def test_failed_mail_request_is_reported(tmp_path):
    http = FakeHttp({LOGIN: [(200, {"loginType": "verifyCode"})],
                     SEND: [(429, {"message": "too many requests"})]})
    bambu = Bambu(tmp_path / "bambu.json", http)
    with pytest.raises(BambuError, match="too many requests"):
        await bambu.login("a@b.de", "pw")
    assert bambu.pending == "code"  # the code can still be requested again


async def test_expired_code_sends_a_new_one(tmp_path):
    http = FakeHttp({LOGIN: [(200, {"loginType": "verifyCode"}), (400, {"code": 1})],
                     SEND: [(200, {}), (200, {})]})
    bambu = Bambu(tmp_path / "bambu.json", http)
    await bambu.login("a@b.de", "pw")
    with pytest.raises(BambuError, match="abgelaufen"):
        await bambu.submit_code("1")
    assert sum(1 for c in http.calls if c[1] == SEND) == 2


def test_spool_from_the_cloud():
    s = to_spool({"id": 5, "filamentVendor": "Bambu Lab", "filamentType": "PLA",
                  "filamentName": "PLA Basic", "color": "#FFFFFFFF", "colors": ["#0A2989FF"],
                  "netWeight": 931, "totalNetWeight": 1000, "status": 0, "RFID": "AB"})
    assert (s.color, s.remaining_g, s.total_g, s.archived, s.rfid) == ("0A2989", 931, 1000,
                                                                        False, "AB")
