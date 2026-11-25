"""Tests of generated images: the `generated_image` element of the plan, and the image generator's script
with the image model mocked.

  python3 -m unittest tests.test_generated_image -v
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_gates import (ROOT, Folder, bash_payload, docs, due_agents, fixture_plan, hook_ctx_of,  # noqa: E402
                        judge_input, png_bytes)
from test_wall_and_blocks import plan_of, wall  # noqa: E402

import base64  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
from unittest import mock  # noqa: E402

sys.path.insert(0, str(ROOT / "images"))
import generate_image  # noqa: E402

GEN = "generated_image · the garden in its first summer, seen from the gate · style: soft watercolour, muted greens"


def gen_plan(*elements: str) -> str:
    """plan_of with every `generated_image` element given what it shows and its style."""
    return plan_of(*elements).replace("generated_image · what it says", GEN)


class PlanElement(unittest.TestCase):
    def read(self, line: str):
        return docs.read_plan(f"- S1 · **Garden** · the garden · 4 lines\n  - {line}\n")

    def test_the_planner_gives_what_it_shows_its_style_and_its_references(self):
        plans, problems = self.read(f"S1.e1 · {GEN} · references: material/garden.jpg, `material/gate.png` · 4 lines")
        self.assertEqual(problems, [])
        r = plans[3][0]
        self.assertEqual(r.get("says"), "the garden in its first summer, seen from the gate")
        self.assertEqual(r.get("style"), "soft watercolour, muted greens")
        self.assertEqual(docs.plan_references(r), ["material/garden.jpg", "material/gate.png"])
        self.assertIn("style: soft watercolour", docs.level_text(plans[3]))  # the approval and the judges see it

    def test_references_are_optional(self):
        plans, problems = self.read(f"S1.e1 · {GEN} · 4 lines")
        self.assertEqual(problems, [])
        self.assertEqual(docs.plan_references(plans[3][0]), [])

    def test_a_generated_image_without_a_style_fails(self):
        _, problems = self.read("S1.e1 · generated_image · the garden in summer · 4 lines")
        self.assertTrue(any("style" in p for p in problems), problems)

    def test_a_field_named_twice_fails(self):
        _, problems = self.read(f"S1.e1 · {GEN} · style: flat · 4 lines")
        self.assertTrue(any("twice" in p for p in problems), problems)

    def test_an_unnamed_extra_field_fails(self):
        _, problems = self.read(f"S1.e1 · {GEN} · a wide picture · 4 lines")
        self.assertTrue(any("named" in p for p in problems), problems)

    def test_other_kinds_read_as_before(self):
        plans, problems = self.read("S1.e1 · paragraph · the garden · facts: F1 · 4 lines")
        self.assertEqual(problems, [])
        self.assertEqual(plans[3][0].get("facts"), "F1")
        self.assertEqual(plans[3][0].get("style"), "")

    def test_it_is_a_picture_and_breaks_a_run_of_plain_text(self):
        self.assertTrue(docs.is_figure_kind("generated_image"))
        self.assertEqual(wall(gen_plan("paragraph:12", "generated_image:3", "paragraph:6")), [])


KEY = "test-key-not-real-0123"
PROMPT = """## Prompt
A small garden pump beside a stone well, seen from the side, no text, no letters, no labels.

## Style
flat, two colours

## References
- `material/pump.png`
"""


class FakeModel:
    """Stands in for the image model: records each call and answers from a list of (status, body)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, body, key):
        self.calls.append({"url": url, "body": body, "key": key})
        return self.answers.pop(0)


def picture(data: bytes, mime: str = "image/png") -> tuple[int, bytes]:
    return 200, json.dumps({"candidates": [{"content": {"parts": [
        {"text": "here it is"}, {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]}}]}).encode()


class Generator(unittest.TestCase):
    def setUp(self):
        self.f = Folder()
        self.folder = self.f.path
        (self.folder / "material").mkdir(exist_ok=True)
        (self.folder / "material" / "pump.png").write_bytes(png_bytes(seed=7))
        attempt = self.folder / ".images" / "S1.e2"
        attempt.mkdir(parents=True)
        (attempt / "1.prompt.md").write_text(PROMPT)
        self.env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": KEY, "GOOGLE_API_KEY": "other-key"}, clear=False)
        self.env.start()
        os.environ.pop("UNSLOPABLE_IMAGE_MODEL", None)
        self.nopause = mock.patch.object(generate_image, "RETRY_PAUSE", 0)
        self.nopause.start()

    def tearDown(self):
        self.nopause.stop()
        self.env.stop()
        self.f.close()

    def run_main(self, model, *extra):
        out = io.StringIO()
        with mock.patch.object(generate_image, "post", model), contextlib.redirect_stdout(out):
            code = generate_image.main(["--folder", str(self.folder), "--prompt-file", ".images/S1.e2/1.prompt.md",
                                        "--out", ".images/S1.e2/1.png", *extra])
        return code, out.getvalue().strip()

    def test_it_sends_the_prompt_the_style_and_the_references_and_writes_the_picture(self):
        model = FakeModel(picture(png_bytes(seed=3)))
        code, printed = self.run_main(model)
        self.assertEqual(code, 0, printed)
        out = self.folder / ".images" / "S1.e2" / "1.png"
        self.assertEqual(Path(printed).resolve(), out.resolve())
        self.assertEqual(out.read_bytes(), png_bytes(seed=3))
        call = model.calls[0]
        parts = call["body"]["contents"][0]["parts"]
        self.assertEqual(base64.b64decode(parts[0]["inlineData"]["data"]), png_bytes(seed=7))  # the reference first
        self.assertIn("stone well", parts[-1]["text"])
        self.assertIn("Style: flat, two colours", parts[-1]["text"])
        self.assertEqual(call["body"]["generationConfig"]["imageConfig"]["aspectRatio"], "16:9")
        self.assertIn(generate_image.DEFAULT_MODEL, call["url"])

    def test_the_key_and_the_model_come_from_the_environment_and_the_key_stays_out_of_the_url(self):
        model = FakeModel(picture(png_bytes()))
        with mock.patch.dict(os.environ, {"UNSLOPABLE_IMAGE_MODEL": "some-image-model"}):
            self.run_main(model, "--aspect", "4:3")
        call = model.calls[0]
        self.assertEqual(call["key"], KEY)  # GEMINI_API_KEY before GOOGLE_API_KEY
        self.assertNotIn(KEY, call["url"])
        self.assertIn("some-image-model", call["url"])
        self.assertEqual(call["body"]["generationConfig"]["imageConfig"]["aspectRatio"], "4:3")
        os.environ.pop("GEMINI_API_KEY")
        model = FakeModel(picture(png_bytes()))
        self.run_main(model)
        self.assertEqual(model.calls[0]["key"], "other-key")

    def test_no_key_is_an_error_that_names_the_variables_and_writes_nothing(self):
        os.environ.pop("GEMINI_API_KEY")
        os.environ.pop("GOOGLE_API_KEY")
        model = FakeModel()
        code, printed = self.run_main(model)
        self.assertEqual(code, 1)
        self.assertIn("GEMINI_API_KEY", printed)
        self.assertEqual(model.calls, [])
        self.assertFalse(list((self.folder / ".images" / "S1.e2").glob("1.png")))

    def test_a_failed_call_is_tried_once_more(self):
        model = FakeModel((500, b"busy"), picture(png_bytes(seed=4)))
        code, printed = self.run_main(model)
        self.assertEqual(code, 0, printed)
        self.assertEqual(len(model.calls), 2)

    def test_an_error_never_shows_the_key(self):
        model = FakeModel((400, f"bad key {KEY}".encode()), (400, f"bad key {KEY}".encode()))
        code, printed = self.run_main(model)
        self.assertEqual(code, 1)
        self.assertTrue(printed.startswith("ERROR:"), printed)
        self.assertNotIn(KEY, printed)

    def test_no_picture_in_the_answer_is_an_error(self):
        empty = (200, json.dumps({"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}).encode())
        code, printed = self.run_main(FakeModel(empty, empty))
        self.assertEqual(code, 1)
        self.assertIn("no picture", printed)

    def test_a_jpeg_answer_gets_the_jpg_extension(self):
        code, printed = self.run_main(FakeModel(picture(b"\xff\xd8jpeg", "image/jpeg")))
        self.assertEqual(code, 0)
        self.assertTrue(printed.endswith("1.jpg"), printed)

    def test_a_missing_reference_is_an_error(self):
        (self.folder / "material" / "pump.png").unlink()
        model = FakeModel()
        code, printed = self.run_main(model)
        self.assertEqual(code, 1)
        self.assertIn("material/pump.png", printed)
        self.assertEqual(model.calls, [])

    def test_the_accepted_picture_copied_into_figures_goes_to_the_generated_image_judge(self):
        plan = fixture_plan().replace(
            "S1.e2 · figure · the path of the water · 4 lines",
            "S1.e2 · generated_image · a garden pump beside a stone well · style: flat, two colours · "
            "references: material/pump.png · 4 lines")
        (self.folder / "PLAN.md").write_text(plan)
        code, printed = self.run_main(FakeModel(picture(png_bytes(seed=3))))
        self.assertEqual(code, 0, printed)
        (self.folder / "figures").mkdir(exist_ok=True)
        att = self.folder / ".images" / "S1.e2"
        fig = self.folder / "figures"
        # the command the agent's prompt gives: the prompt file first, then the picture, absolute paths
        command = (f"cp {shlex.quote(str(att / '1.prompt.md'))} {shlex.quote(str(fig / 'S1.e2.prompt.md'))} && "
                   f"cp {shlex.quote(str(att / '1.png'))} {shlex.quote(str(fig / 'S1.e2.png'))}")
        self.assertEqual(os.system(command), 0)
        ctx = hook_ctx_of(bash_payload(self.folder, command))
        self.assertNotIn("is missing", ctx)
        self.assertIn("unslopable:gate-generated-image", due_agents(self.folder))
        self.assertNotIn("unslopable:gate-screenshot-cropped", due_agents(self.folder))
        inp = judge_input(self.folder, "generated-image")
        self.assertIn("stone well", inp)
        self.assertIn("material/pump.png", inp)


    def test_a_refusal_or_a_client_error_is_not_tried_again(self):
        safety = (200, json.dumps({"candidates": [{"finishReason": "SAFETY"}]}).encode())
        for answer in (safety, (403, b"forbidden"), (404, b"no such model")):
            with self.subTest(status=answer[0]):
                model = FakeModel(answer, picture(png_bytes()))
                code, _ = self.run_main(model)
                self.assertEqual(code, 1)
                self.assertEqual(len(model.calls), 1)
        model = FakeModel((429, b"slow down"), picture(png_bytes()))
        self.assertEqual(self.run_main(model)[0], 0)
        self.assertEqual(len(model.calls), 2)

    def test_a_broken_answer_is_an_error_line_not_a_traceback(self):
        bad_b64 = (200, json.dumps({"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": "not base64 !!"}}]}}]}).encode())
        for answer in (bad_b64, (200, b"[1, 2]"), (200, b"not json")):
            with self.subTest(body=answer[1][:20]):
                code, printed = self.run_main(FakeModel(answer, answer))
                self.assertEqual(code, 1)
                self.assertTrue(printed.startswith("ERROR:"), printed)

    def test_the_real_call_puts_the_key_in_a_header_and_never_in_the_url(self):
        seen = {}

        class Answer:
            status = 200

            def read(self):
                return picture(png_bytes())[1]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout):
            seen["url"], seen["key"] = req.full_url, req.get_header("X-goog-api-key")
            return Answer()

        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", urlopen), contextlib.redirect_stdout(out):
            code = generate_image.main(["--folder", str(self.folder), "--prompt-file", ".images/S1.e2/1.prompt.md",
                                        "--out", ".images/S1.e2/1.png"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(seen["key"], KEY)
        self.assertNotIn(KEY, seen["url"])

    def test_an_image_with_no_references_passes_its_prompt_file_script(self):
        plan = fixture_plan().replace(
            "S1.e2 · figure · the path of the water · 4 lines",
            "S1.e2 · generated_image · a garden pump beside a stone well · style: flat, two colours · 4 lines")
        (self.folder / "PLAN.md").write_text(plan)
        att = self.folder / ".images" / "S1.e2"
        for seed, refs in enumerate(("", "none\n", "- none\n"), 10):
            with self.subTest(refs=refs):
                (att / "1.prompt.md").write_text(PROMPT.split("## References")[0] + "## References\n" + refs)
                self.assertEqual(self.run_main(FakeModel(picture(png_bytes(seed=seed))))[0], 0)
                fig = self.folder / "figures"
                fig.mkdir(exist_ok=True)
                command = (f"cp {shlex.quote(str(att / '1.prompt.md'))} {shlex.quote(str(fig / 'S1.e2.prompt.md'))} && "
                           f"cp {shlex.quote(str(att / '1.png'))} {shlex.quote(str(fig / 'S1.e2.png'))}")
                self.assertEqual(os.system(command), 0)
                ctx = hook_ctx_of(bash_payload(self.folder, command))
                self.assertNotIn("does not exist", ctx)
                self.assertIn("unslopable:gate-generated-image", due_agents(self.folder))


class Wiring(unittest.TestCase):
    def test_the_writer_hands_generated_images_to_the_generator(self):
        writer = (ROOT / "skills" / "writer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("unslopable:image-generator", writer)
        self.assertIn("generated_image", writer)
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("./agents/image-generator.md", manifest["agents"])

    def test_the_agent_writes_the_prompt_file_the_gate_reads(self):
        agent = (ROOT / "agents" / "image-generator.md").read_text(encoding="utf-8")
        for part in ("## Prompt", "## Style", "## References", "images/generate_image.py", ".images/", "figures/"):
            self.assertIn(part, agent)


if __name__ == "__main__":
    unittest.main()
