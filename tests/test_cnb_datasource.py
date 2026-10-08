import base64
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


from dify_plugin.entities.datasource import (
    DatasourceMessage,
    GetOnlineDocumentPageContentRequest,
)

from datasources.cnb import CNBAPIError, CNBDataSource
from provider.cnb import CNBDatasourceProvider


def build_datasource(credentials=None):
    datasource = object.__new__(CNBDataSource)
    datasource.runtime = SimpleNamespace(
        credentials=credentials
        or {
            "access_token": "test-token",
            "cnb_api_base_url": "https://api.cnb.cool",
            "cnb_web_url": "https://cnb.cool",
        }
    )
    datasource.response_type = DatasourceMessage
    return datasource


class CNBDataSourceTest(unittest.TestCase):
    def test_headers(self):
        datasource = build_datasource()
        self.assertEqual(
            datasource._get_headers()["Authorization"],
            "Bearer test-token",
        )

    def test_get_pages(self):
        datasource = build_datasource()

        def fake_request(method, path, params=None):
            if path == "/user":
                return {
                    "id": "u1",
                    "username": "alice",
                    "nickname": "Alice",
                    "avatar": "https://example.com/alice.png",
                }
            if path == "/user/repos":
                return [
                    {
                        "path": "team/demo",
                        "name": "demo",
                        "last_updated_at": "2026-09-30T08:00:00Z",
                    }
                ]
            if path == "/team/demo/-/git/contents":
                return {
                    "entries": [
                        {"name": "README.md", "path": "README.md", "type": "blob"}
                    ]
                }
            if path == "/team/demo/-/issues":
                return [
                    {
                        "number": "8",
                        "title": "Fix import",
                        "updated_at": "2026-09-30T09:00:00Z",
                    }
                ]
            if path == "/team/demo/-/pulls":
                return [
                    {
                        "number": "3",
                        "title": "Add connector",
                        "updated_at": "2026-09-30T10:00:00Z",
                    }
                ]
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        response = datasource._get_pages({"max_repos": 10})
        workspace = response.result[0]
        self.assertEqual(workspace.workspace_name, "Alice's CNB")
        self.assertEqual(
            [page.page_id for page in workspace.pages],
            [
                "project:team/demo",
                "file:team/demo:README.md",
                "issue:team/demo:8",
                "pull:team/demo:3",
            ],
        )
        self.assertEqual(workspace.pages[1].parent_id, "project:team/demo")

    def test_read_file_decodes_base64(self):
        datasource = build_datasource()
        encoded = base64.b64encode(b"# Hello").decode("ascii")
        datasource._request = lambda method, path, params=None: {
            "type": "blob",
            "encoding": "base64",
            "content": encoded,
        }
        self.assertEqual(datasource._read_file("team/demo", "docs/a.md"), "# Hello")

    def test_forbidden_error_includes_cnb_scope_details(self):
        datasource = build_datasource()
        response = Mock(
            status_code=403,
            text=(
                '{"errcode":10023,"errmsg":"Missing required scopes: '
                'repo-basic-info:r"}'
            ),
        )

        with self.assertRaises(CNBAPIError) as context:
            datasource._raise_api_error(response)

        self.assertIn("repo-basic-info:r", str(context.exception))

    def test_zero_max_repos_uses_default(self):
        datasource = build_datasource()
        captured = []
        datasource._get_user = lambda: {"id": "u1", "username": "alice"}
        datasource._get_repositories = lambda max_repos, repository_paths=None: (
            captured.append(max_repos) or []
        )

        datasource._get_pages({"max_repos": 0})

        self.assertEqual(captured, [20])

    def test_list_code_files(self):
        datasource = build_datasource()

        def fake_request(method, path, params=None):
            if path == "/team/demo/-/git/contents":
                return {
                    "entries": [
                        {"path": "README.md", "type": "blob"},
                        {"path": "src", "type": "tree"},
                        {"path": "logo.png", "type": "blob"},
                    ]
                }
            if path == "/team/demo/-/git/contents/src":
                return {
                    "entries": [
                        {"path": "src/app.py", "type": "blob"},
                        {"path": "src/package-lock.json", "type": "blob"},
                        {"path": "src/node_modules", "type": "tree"},
                    ]
                }
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        self.assertEqual(
            datasource._list_code_files("team/demo", 100),
            ["src/app.py"],
        )

    def test_format_languages(self):
        datasource = build_datasource()
        self.assertEqual(
            datasource._format_languages(
                {"languages": {"language": "Vue", "color": "#41b883"}}
            ),
            "Vue",
        )

    def test_parse_repository_paths(self):
        datasource = build_datasource()
        self.assertEqual(
            datasource._parse_repository_paths(
                "organization/group/repository-a\n"
                "https://cnb.cool/organization/group/repository-b.git, "
                "https://cnb.cool/organization/group/repository-c/-/blob/main/README.md, "
                "organization/group/repository-b"
            ),
            [
                "organization/group/repository-a",
                "organization/group/repository-b",
                "organization/group/repository-c",
            ],
        )

    def test_normalize_ref(self):
        datasource = build_datasource()
        self.assertEqual(datasource._normalize_ref("refs/heads/develop"), "develop")
        self.assertEqual(
            datasource._normalize_ref(
                "https://cnb.cool/organization/group/repository/-/tree/release"
            ),
            "release",
        )

    def test_resolve_ref_type_explicitly(self):
        datasource = build_datasource()

        def fake_request(method, path, params=None):
            if path == "/team/demo/-/git/branches/release":
                return {"commit": {"sha": "branch-sha"}}
            if path == "/team/demo/-/git/tags/release":
                return {"commit": {"sha": "tag-sha"}}
            if path == "/team/demo/-/git/commits/abc123":
                return {"sha": "commit-sha"}
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        self.assertEqual(
            datasource._resolve_ref("team/demo", "release", "branch"),
            "branch-sha",
        )
        self.assertEqual(
            datasource._resolve_ref("team/demo", "release", "tag"),
            "tag-sha",
        )
        self.assertEqual(
            datasource._resolve_ref("team/demo", "abc123", "commit"),
            "commit-sha",
        )

    def test_ref_selection_allows_only_one_field(self):
        datasource = build_datasource()
        self.assertEqual(
            datasource._get_ref_selection({"branch": "develop"}),
            ("branch", "develop"),
        )
        self.assertEqual(
            datasource._get_ref_selection({"tag": "v1.0.0"}),
            ("tag", "v1.0.0"),
        )
        self.assertEqual(
            datasource._get_ref_selection({"commit": "abc123"}),
            ("commit", "abc123"),
        )
        with self.assertRaises(ValueError):
            datasource._get_ref_selection({"branch": "develop", "tag": "v1.0.0"})

    def test_get_pages_with_ref(self):
        datasource = build_datasource()
        calls = []

        def fake_request(method, path, params=None):
            calls.append((path, params))
            if path == "/user":
                return {"id": "u1", "username": "alice"}
            if path == "/team/demo/-/git/branches/develop":
                return {"commit": {"sha": "resolved-develop"}}
            if path == "/team/demo/-/git/contents":
                return {
                    "entries": [
                        {"name": "README.md", "path": "README.md", "type": "blob"}
                    ]
                }
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        response = datasource._get_pages(
            {
                "repository_paths": "team/demo",
                "branch": "develop",
                "max_files_per_repo": 0,
                "issues_per_repo": 0,
                "pulls_per_repo": 0,
            }
        )

        pages = response.result[0].pages
        encoded_ref = (
            base64.urlsafe_b64encode(b"resolved-develop").decode("ascii").rstrip("=")
        )
        self.assertEqual(
            [page.page_id for page in pages],
            [
                f"project:team/demo|{encoded_ref}",
                f"file:team/demo|{encoded_ref}:README.md",
            ],
        )
        self.assertIn(
            ("/team/demo/-/git/contents", {"ref": "resolved-develop"}),
            calls,
        )

    def test_ref_permission_error_skips_repo_content(self):
        datasource = build_datasource()

        def fake_request(method, path, params=None):
            if path == "/user":
                return {"id": "u1", "username": "alice"}
            if path == "/team/demo/-/git/branches/develop":
                return {"commit": {"sha": "resolved-develop"}}
            if path == "/team/demo/-/git/contents":
                raise CNBAPIError(403, "you do not have permission")
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        response = datasource._get_pages(
            {
                "repository_paths": "team/demo",
                "branch": "develop",
                "max_files_per_repo": 100,
                "issues_per_repo": 0,
                "pulls_per_repo": 0,
            }
        )

        pages = response.result[0].pages
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page_name, "demo (develop unavailable)")

    def test_repository_scoped_credentials_skip_account_apis(self):
        datasource = build_datasource(
            credentials={
                "access_token": "test-token",
                "cnb_api_base_url": "https://api.cnb.cool",
                "cnb_web_url": "https://cnb.cool",
                "repository_path": "team/demo",
            }
        )
        calls = []

        def fake_request(method, path, params=None):
            calls.append(path)
            if path == "/team/demo/-/git/contents":
                return {"entries": []}
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        response = datasource._get_pages(
            {
                "max_files_per_repo": 0,
                "issues_per_repo": 0,
                "pulls_per_repo": 0,
            }
        )

        self.assertEqual(response.result[0].workspace_name, "CNB Repositories")
        self.assertNotIn("/user", calls)
        self.assertNotIn("/user/repos", calls)

    def test_issue_content(self):
        datasource = build_datasource()

        def fake_request(method, path, params=None):
            if path == "/team/demo/-/issues/8":
                return {
                    "number": "8",
                    "title": "Fix import",
                    "body": "Issue body",
                    "author": {"username": "alice", "nickname": "Alice"},
                    "state": "open",
                    "labels": [{"name": "bug"}],
                }
            if path == "/team/demo/-/issues/8/comments":
                return [
                    {
                        "body": "A comment",
                        "author": {"username": "bob"},
                        "created_at": "2026-09-30T09:01:00Z",
                    }
                ]
            raise AssertionError(f"unexpected path: {path}")

        datasource._request = fake_request
        page = GetOnlineDocumentPageContentRequest(
            workspace_id="u1",
            page_id="issue:team/demo:8",
            type="issue",
        )
        messages = list(datasource._get_content(page))
        variables = {
            message.message.variable_name: message.message.variable_value
            for message in messages
        }
        self.assertIn("Issue body", variables["content"])
        self.assertIn("A comment", variables["content"])
        self.assertEqual(variables["issue_number"], "8")


class CNBProviderTest(unittest.TestCase):
    def test_validate_credentials(self):
        provider = CNBDatasourceProvider()
        response = Mock(status_code=200, text="")
        session = Mock()
        session.get.return_value = response

        with patch.object(provider, "_get_requests_session", return_value=session):
            provider._validate_credentials({"access_token": "secret"})

        session.get.assert_called_once()
        self.assertEqual(
            session.get.call_args.kwargs["headers"]["Authorization"],
            "Bearer secret",
        )

    def test_validate_repository_scoped_credentials(self):
        provider = CNBDatasourceProvider()
        response = Mock(status_code=200, text="")
        session = Mock()
        session.get.return_value = response

        with patch.object(provider, "_get_requests_session", return_value=session):
            provider._validate_credentials(
                {
                    "access_token": "secret",
                    "repository_path": "team/demo",
                }
            )

        self.assertEqual(session.get.call_count, 2)
        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(
            urls,
            [
                "https://api.cnb.cool/team/demo",
                "https://api.cnb.cool/team/demo/-/git/contents",
            ],
        )


if __name__ == "__main__":
    unittest.main()
