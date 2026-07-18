import threading
import unittest
from queue import SimpleQueue

from bsense_experiment.app import BSenseExperimentApp


class FakeRoot:
    def __init__(self) -> None:
        self.after_threads: list[int] = []
        self.exists = True

    def after(self, _milliseconds: int, _callback: object) -> str:
        self.after_threads.append(threading.get_ident())
        return "poll-1"

    def winfo_exists(self) -> bool:
        return self.exists


class AppAsyncTests(unittest.TestCase):
    def test_worker_posts_ui_action_without_calling_tk(self) -> None:
        app = BSenseExperimentApp.__new__(BSenseExperimentApp)
        app.root = FakeRoot()
        app.ui_actions = SimpleQueue()
        app.ui_action_poll_id = None
        callback_threads: list[int] = []
        main_thread = threading.get_ident()

        worker = threading.Thread(target=lambda: app._post_to_ui(lambda: callback_threads.append(threading.get_ident())))
        worker.start()
        worker.join()

        self.assertEqual(app.root.after_threads, [])
        app._poll_ui_actions()
        self.assertEqual(callback_threads, [main_thread])
        self.assertEqual(app.root.after_threads, [main_thread])
        self.assertEqual(app.ui_action_poll_id, "poll-1")


if __name__ == "__main__":
    unittest.main()
