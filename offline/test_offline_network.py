"""Verify the actual macOS guard, including IPv6 and the local save link."""

# Regression checks for offline network.
# Read each test name with its assertions to see the behavior being protected.
# Fixtures/mocks belong in temporary storage; never point them at the real save.
# Run this file with unittest discovery; see docs/05-source-guide.md.

import json, platform, socket, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == "Darwin", "macOS network guard")
class OfflineNetworkTests(unittest.TestCase):
    def test_local_connection_allowed_external_connections_denied(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            script = """
import errno,json,socket,sys
local=socket.socket();local.settimeout(2)
local.connect(('127.0.0.1',int(sys.argv[1])));local.close()
results=[]
for family,kind,host in [(socket.AF_INET,socket.SOCK_STREAM,'1.1.1.1'),(socket.AF_INET,socket.SOCK_STREAM,'192.168.1.1'),(socket.AF_INET,socket.SOCK_DGRAM,'1.1.1.1'),(socket.AF_INET6,socket.SOCK_STREAM,'2606:4700:4700::1111')]:
    with socket.socket(family,kind) as client:
        client.settimeout(2)
        try:
            if kind==socket.SOCK_DGRAM:client.sendto(b'offline-test',(host,443));result=0
            else:result=client.connect_ex((host,443))
        except OSError as error:result=error.errno
        results.append(result)
print(json.dumps(results))
"""
            result = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-f",
                    str(ROOT / "launcher/offline.sb"),
                    sys.executable,
                    "-B",
                    "-c",
                    script,
                    str(listener.getsockname()[1]),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            import errno

            self.assertEqual(json.loads(result.stdout), [errno.EPERM] * 4)
            connection, _ = listener.accept()
            connection.close()


if __name__ == "__main__":
    unittest.main()
