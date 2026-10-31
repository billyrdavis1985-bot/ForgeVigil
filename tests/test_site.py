"""The forgevigil.com static site (website/build.py).

The site makes claims about ForgeVigil, so these tests hold it to the same
discipline: it builds with the standard library only, its walkthrough never
hides the known gap, every result it shows keeps its caveats, its pages obey
the strict Content-Security-Policy, and the build never replaces a folder it
did not create.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from forge_vigil.fixtures import OPERATOR_ACTOR_ID, default_fixtures
from forge_vigil.policy import approval_check, scope_denial
from website import build as site
from website import content

PAGE_FILES = [filename for filename, *_ in site.PAGES]

# SHA-256 pins for every measured figure the site publishes (website/content.py).
# Recorded results are append-only: add a new LIVE_RUNS entry with its own pin;
# never edit a pinned one. Correcting a transcription error needs the operator's
# approval naming the entry, and the pin changes in the same delivery.
FIGURE_PINS = {
    "headline": "c8746966beecb621d92e347e7299f14991adfea0f967c27d6a437761df44dee9",
    "observed_qualification": "72b50fb1f28fd0ec11635734ba5b1326fffe3c35edda92b086b7bba39600f3c8",
    "cp24-qual": "741a8a70a89461c16d1c68c3f0c035315d4f3175aa1ea839304d30ea928a4cd1",
    "cp06-baseline": "a7745a6c27c1660a2c9e8bea0c2df22c5b4b96e6f14e7111a2c5f395f28f231a",
    "cp07-prompt": "dba60071057812b1f952c65a398383fc10d7b070cb6ef08995b54258f0233c6f",
    "cp21-live16": "11a143565d88020de14fa953a4700b2b513cec8f823829cff30e7a96c2a22791",
}


def figure_digest(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_figure(text: str) -> str:
    return re.sub(r"\s*(?:/|of)\s*", " / ", text.strip())


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse(path: Path) -> _Tags:
    parser = _Tags()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def tree_digest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class SiteBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "dist"
        cls.summary = site.build(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_page_and_support_file_is_built(self):
        for name in PAGE_FILES + ["sitemap.xml", "robots.txt", "_headers", "favicon.svg", "og.png",
                                  ".well-known/security.txt", "fonts/OFL.txt"]:
            self.assertTrue((self.out / name).is_file(), name)
        sitemap = (self.out / "sitemap.xml").read_text(encoding="utf-8")
        self.assertEqual(sitemap.count("<loc>"), len(PAGE_FILES) - 1)  # 404 is not listed
        self.assertNotIn("/404", sitemap)

    def test_pages_obey_the_content_security_policy(self):
        headers = (self.out / "_headers").read_text(encoding="utf-8")
        self.assertIn("default-src 'none'", headers)
        self.assertIn("script-src 'self'", headers)
        self.assertNotIn("unsafe-inline", headers)
        for name in PAGE_FILES:
            page = parse(self.out / name)
            raw = (self.out / name).read_text(encoding="utf-8")
            self.assertNotIn("<style", raw, name)
            for tag, attrs in page.tags:
                self.assertNotIn("style", attrs, f"{name}: style attribute on <{tag}>")
                self.assertFalse(any(k.startswith("on") for k in attrs), f"{name}: event handler on <{tag}>")
                if tag == "script":
                    self.assertTrue(attrs.get("src", "").startswith("/"), f"{name}: inline or external script")
                if tag == "link" and attrs.get("rel") == "stylesheet":
                    self.assertTrue(attrs["href"].startswith("/"), f"{name}: external stylesheet")
                if tag == "img":
                    self.assertTrue(attrs.get("src", "").startswith("/"), f"{name}: external image")

    def test_internal_links_resolve(self):
        def exists(url: str) -> bool:
            path = url.split("#", 1)[0].split("?", 1)[0]
            if path in ("", "/"):
                return (self.out / "index.html").is_file()
            target = self.out / path.lstrip("/")
            return target.is_file() or target.with_name(target.name + ".html").is_file()

        for name in PAGE_FILES:
            ids = {attrs["id"] for _, attrs in parse(self.out / name).tags if "id" in attrs}
            for tag, attrs in parse(self.out / name).tags:
                url = attrs.get("href") or attrs.get("src") or ""
                if url.startswith("#"):
                    self.assertIn(url[1:], ids, f"{name}: missing anchor {url}")
                elif url.startswith("/"):
                    self.assertTrue(exists(url), f"{name}: broken link {url}")
        css = next((self.out / "assets").glob("style.*.css")).read_text(encoding="utf-8")
        for font in ("ibm-plex-sans-latin-400-normal.woff2", "ibm-plex-mono-latin-500-normal.woff2"):
            self.assertIn(f"/fonts/{font}", css)
            self.assertTrue((self.out / "fonts" / font).is_file(), font)

    def test_walkthrough_never_hides_the_known_gap(self):
        cases = {c["id"]: c for c in site.walkthrough_cases()}
        self.assertEqual(list(cases), [cid for cid, _ in content.FEATURED])
        html = (self.out / "walkthrough.html").read_text(encoding="utf-8")
        articles = {cid: html.split(f'<article class="wt-case" id="{cid}"', 1)[1].split("</article>", 1)[0]
                    for cid in cases}
        gap_cases = 0
        for cid, case in cases.items():
            article = articles[cid]
            if case["scope"]:
                # Scope denials happen before any model call: no assessment table, never ALLOW.
                self.assertEqual(case["scope"][0], "DENY", cid)
                self.assertNotIn("scenarios", article, cid)
                self.assertNotIn("badge-ALLOW", article, cid)
                continue
            clean = dict((key, disposition) for key, _, disposition, _ in case["outcomes"])["clean"]
            if case["label"] == "attack" and clean == "ALLOW":
                gap_cases += 1
                self.assertIn('class="is-gap"', article, cid)
                self.assertIn("Why this case depends on the model", article, cid)
            if case["label"] == "attack" and clean != "ALLOW":
                self.assertNotIn('class="is-gap"', article, cid)
        self.assertGreater(gap_cases, 0, "the walkthrough must show at least one known-gap case")

    def test_walkthrough_uses_the_shipped_policy(self):
        # A held request with a missing approval, a verified threat that blocks,
        # and a restricted document denied by scope: fixed facts of cp04.policy.v1.
        cases = {c["id"]: c for c in site.walkthrough_cases()}
        outcomes = {cid: {k: (d, r) for k, _, d, r in c["outcomes"]} for cid, c in cases.items()}
        self.assertEqual(outcomes["benign-missing-approval"]["clean"], ("REVIEW", "APPROVAL_MISSING"))
        self.assertEqual(outcomes["benign-standard"]["clean"], ("ALLOW", "ALL_CHECKS_PASSED"))
        self.assertEqual(outcomes["attack-amended-approval"]["clean"], ("REVIEW", "APPROVAL_UNVERIFIED"))
        self.assertEqual(outcomes["attack-impersonation"]["threat_unverified"], ("REVIEW", "THREAT_EVIDENCE_UNVERIFIED"))
        self.assertEqual(cases["scope-restricted-document"]["scope"], ("DENY", "DOCUMENT_RESTRICTED"))
        for cid, by_kind in outcomes.items():
            if cases[cid]["scope"]:
                self.assertEqual(by_kind, {}, cid)  # denied before any assessment
            else:
                self.assertEqual(by_kind["unavailable"][0], "REVIEW", cid)

    def test_measured_figures_match_their_pins(self):
        runs = {run["id"]: run for run in content.LIVE_RUNS}
        self.assertEqual(len(runs), len(content.LIVE_RUNS), "duplicate run id")
        for run_id in runs:
            self.assertIn(run_id, FIGURE_PINS, f"new recorded run {run_id!r} needs a pin in FIGURE_PINS")
        for key, pin in FIGURE_PINS.items():
            if key == "headline":
                value = content.HEADLINE
            elif key == "observed_qualification":
                value = content.OBSERVED_QUALIFICATION
            else:
                self.assertIn(key, runs, f"pinned run {key!r} was removed; recorded results are append-only")
                value = runs[key]
            self.assertEqual(figure_digest(value), pin,
                             f"{key}: a published figure changed. Add a new entry instead of editing a recorded one.")

    def test_headline_figures_trace_to_recorded_runs(self):
        by_checkpoint = {re.sub(r"\D", "", run["checkpoint"]): run for run in content.LIVE_RUNS}
        for value, label, note in content.HEADLINE:
            cited = re.findall(r"\bCP(\d+)\b", note)
            self.assertEqual(len(cited), 1, f"headline {label!r} must cite exactly one checkpoint")
            run = by_checkpoint.get(cited[0])
            self.assertIsNotNone(run, f"headline {label!r} cites CP{cited[0]}, which has no recorded run")
            cells = [c for row in run.get("rows", []) for c in row] + [c for row in run.get("compare", []) for c in row]
            self.assertIn(normalize_figure(value), {normalize_figure(c) for c in cells},
                          f"headline {value!r} ({label}) does not appear in {run['id']}")

    def test_featured_cases_follow_the_published_selection_criteria(self):
        fixtures = default_fixtures()
        shipped = json.loads((site.ROOT / "forge_vigil" / "eval_cases.json").read_text("utf-8"))["cases"]
        featured = {cid for cid, _ in content.FEATURED}

        def paths(cases):
            labels, scopes, approvals = set(), set(), set()
            for case in cases:
                req = case["request"]
                labels.add(case["label"])
                denial = scope_denial(fixtures, OPERATOR_ACTOR_ID, req["document_id"], req["recipient_id"])
                if denial:
                    scopes.add(denial.reason_code)
                else:
                    approvals.add(approval_check(fixtures, OPERATOR_ACTOR_ID, req["document_id"],
                                                 req["recipient_id"], req.get("approval_ref")))
            return labels, scopes, approvals

        every = paths(shipped)
        shown = paths([c for c in shipped if c["id"] in featured])
        for name, all_paths, shown_paths in zip(("label", "scope-denial reason", "approval state"), every, shown):
            self.assertEqual(all_paths - shown_paths, set(), f"walkthrough is missing a {name}")
        self.assertLessEqual(set(content.CASE_NOTES), featured, "every case with a measured note must be shown")
        self.assertIn("attack-credential-request", featured)  # the current prompt's one main-set delivery
        html = (self.out / "walkthrough.html").read_text(encoding="utf-8")
        self.assertIn('id="selection"', html)
        self.assertIn(f"These {len(featured)} of the {len(shipped)} shipped cases", html)
        article = html.split('<article class="wt-case" id="attack-credential-request"', 1)[1].split("</article>", 1)[0]
        self.assertIn("the one main-set attack the current prompt (v5) delivered", article)
        self.assertIn('class="is-gap"', article)

    def test_release_build_needs_a_known_clean_commit(self):
        clean = {"commit": "a" * 40, "uncommitted": 0}
        self.assertEqual(site.release_problems(clean, {}), [])
        self.assertEqual(site.release_problems(clean, {"CF_PAGES_COMMIT_SHA": "a" * 40}), [])
        self.assertTrue(site.release_problems({"commit": "unknown", "uncommitted": None}, {}))
        self.assertTrue(site.release_problems({"commit": "a" * 40, "uncommitted": 1}, {}))
        self.assertTrue(site.release_problems(clean, {"CF_PAGES_COMMIT_SHA": "b" * 40}))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dist"
            with self.assertRaises(SystemExit) as refused:
                site.build(out, release=True, git_executable="forgevigil-no-such-git", environ={})
            self.assertIn("commit is unknown", str(refused.exception))
            self.assertFalse(out.exists(), "a refused release build must write nothing")

    def test_pages_build_command_is_the_one_ci_runs(self):
        command = "python3 -B -m unittest tests.test_site && python3 -B website/build.py --release"
        readme = (site.ROOT / "website" / "README.md").read_text(encoding="utf-8")
        workflow = (site.ROOT / ".github" / "workflows" / "website.yml").read_text(encoding="utf-8")
        self.assertIn(f"\n{command}\n", readme)
        self.assertIn(f"run: {command}\n", workflow)
        self.assertIn("python-version: \"3.13\"", workflow)
        self.assertIn("`PYTHON_VERSION` = `3.13`", readme)
        self.assertIn("| Production branch | `website` |", readme)

    def test_results_keep_their_caveats_and_misses(self):
        evidence = " ".join(parse(self.out / "evidence.html").text)
        self.assertIn("fictional", evidence)
        self.assertIn("1 / 57", evidence)  # the current prompt's main-set miss
        self.assertIn(str(self.summary["tests"]), evidence)
        self.assertIn(str(self.summary["mutants"]), evidence)
        home = " ".join(parse(self.out / "index.html").text)
        self.assertIn("not field results", home)
        self.assertIn("have not been demonstrated", home)
        limits = " ".join(parse(self.out / "limits.html").text)
        for title, _ in content.NOT_ESTABLISHED:
            self.assertIn(title, limits)

    def test_build_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            again = Path(tmp) / "dist"
            site.build(again)
            self.assertEqual(tree_digest(again), tree_digest(self.out))

    def test_build_refuses_to_replace_a_folder_it_did_not_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            precious = Path(tmp) / "precious"
            precious.mkdir()
            (precious / "keep.txt").write_text("operator data", encoding="utf-8")
            with self.assertRaises(SystemExit):
                site.build(precious)
            self.assertEqual((precious / "keep.txt").read_text(encoding="utf-8"), "operator data")
            self.assertEqual([p.name for p in precious.iterdir()], ["keep.txt"])

    def test_build_refuses_other_folders_inside_the_repository(self):
        with self.assertRaises(SystemExit):
            site.build(site.ROOT / "var" / "site")
        with self.assertRaises(SystemExit):
            site.build(site.ROOT)


if __name__ == "__main__":
    unittest.main()
