import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from bsense_experiment.app import LabRecorderClient


class FakeLabRecorder:
    def __init__(self, target: Path, stop_response_delay: float = 0.0) -> None:
        self.target = target
        self.stop_response_delay = stop_response_delay
        self.commands: list[str] = []
        self.port = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()
        self.ready.wait(timeout=3)

    def join(self) -> None:
        self.thread.join(timeout=3)

    def _serve(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        self.port = server.getsockname()[1]
        server.listen(1)
        self.ready.set()
        client, _ = server.accept()
        reader = client.makefile("rb")
        while True:
            line = reader.readline()
            if not line:
                break
            command = line.decode().strip()
            self.commands.append(command)
            if command == "start":
                self.target.write_bytes(b"XDF-START")
            elif command == "stop":
                with self.target.open("ab") as handle:
                    handle.write(b"-STOP")
                time.sleep(self.stop_response_delay)
            client.sendall(b"OK")
            if command == "stop":
                break
        client.close()
        server.close()


class LabRecorderClientTests(unittest.TestCase):
    def test_start_and_stop_with_file_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filename = "sub-pilot01_ses-01_task-deviceqc_run-001.xdf"
            target = root / filename
            server = FakeLabRecorder(target, stop_response_delay=0.1)
            server.start()

            client = LabRecorderClient("127.0.0.1", server.port)
            client.timeout = 0.05
            original_command = client.command

            def command_without_refresh_delay(command: str, response_timeout: float | None = None) -> str:
                if command == "update":
                    client._record_diagnostic("test_refresh_delay_bypassed")
                return original_command(command, response_timeout=response_timeout)

            client.command = command_without_refresh_delay  # type: ignore[method-assign]
            path, initial_size = client.start_recording(root, filename)
            final_size = client.stop_recording(path)
            server.join()

            self.assertEqual(initial_size, 9)
            self.assertEqual(final_size, 14)
            self.assertEqual(server.commands[0], "update")
            self.assertEqual(server.commands[-1], "stop")
            self.assertIn("select all", server.commands)
            self.assertIn("start", server.commands)

            diagnostic_path = root / "recorder.jsonl"
            client.write_diagnostics(diagnostic_path)
            records = [json.loads(line) for line in diagnostic_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(record["event"] == "xdf_created" for record in records))
            self.assertTrue(any(record["event"] == "xdf_closed" for record in records))


if __name__ == "__main__":
    unittest.main()
