"""Imported first by every test module: the plugin's cache (the gate hook's log, the list of documents) goes to a
temp folder, never to the author's real `~/.cache/unslopable`. Subprocesses inherit it through the environment."""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("UNSLOPABLE_CACHE", "").startswith(tempfile.gettempdir()):
    os.environ["UNSLOPABLE_CACHE"] = tempfile.mkdtemp(prefix="unslopable-cache-")
    atexit.register(shutil.rmtree, os.environ["UNSLOPABLE_CACHE"], True)
