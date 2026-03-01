#!/usr/bin/env python3
import unittest

from service_supervisor import SupervisorBridgeService


class SupervisorBridgeTests(unittest.TestCase):
    def test_parse_supervisor_status(self):
        text = "service-a RUNNING pid 1, uptime 0:00:10\nservice-b BACKOFF Exited too quickly"
        rows = SupervisorBridgeService._parse_supervisor_status(text)
        self.assertEqual(2, len(rows))
        self.assertEqual("service-a", rows[0]["name"])
        self.assertEqual("RUNNING", rows[0]["state"])
        self.assertEqual("service-b", rows[1]["name"])
        self.assertEqual("BACKOFF", rows[1]["state"])

    def test_handle_request_unknown(self):
        svc = SupervisorBridgeService()
        resp = svc._handle_request({"action": "nope"})
        self.assertEqual("error", resp.get("status"))

    def test_handle_request_ping(self):
        svc = SupervisorBridgeService()
        resp = svc._handle_request({"action": "ping"})
        self.assertEqual("ok", resp.get("status"))
        self.assertEqual("service-supervisor", resp.get("service"))


if __name__ == "__main__":
    unittest.main()
