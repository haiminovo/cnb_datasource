import base64
import binascii
from collections.abc import Generator, Mapping
from typing import Any, ClassVar
from urllib.parse import quote, unquote, urlparse

import certifi
import requests
from dify_plugin.entities.datasource import (
    DatasourceGetPagesResponse,
    DatasourceMessage,
    GetOnlineDocumentPageContentRequest,
    OnlineDocumentInfo,
)
from dify_plugin.interfaces.datasource.online_document import (
    OnlineDocumentDatasource,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CNBAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class CNBDataSource(OnlineDocumentDatasource):
    _DEFAULT_API_BASE_URL = "https://api.cnb.cool"
    _DEFAULT_WEB_URL = "https://cnb.cool"
    _MAX_TREE_DEPTH = 10
    _MAX_TREE_DIRECTORIES = 200
    _README_CANDIDATES: ClassVar[set[str]] = {
        "readme",
        "readme.md",
        "readme.markdown",
        "readme.mdown",
        "readme.rst",
        "readme.txt",
    }
    _EXCLUDED_DIRECTORIES: ClassVar[set[str]] = {
        ".git",
        ".gradle",
        ".idea",
        ".mvn",
        ".next",
        ".nuxt",
        ".tox",
        ".venv",
        ".vscode",
        "__pycache__",
        "bin",
        "build",
        "coverage",
        "dist",
        "logs",
        "node_modules",
        "obj",
        "out",
        "target",
        "temp",
        "tmp",
        "vendor",
        "venv",
    }
    _CODE_FILE_EXTENSIONS: ClassVar[set[str]] = {
        ".adoc",
        ".astro",
        ".bash",
        ".c",
        ".cc",
        ".cfg",
        ".clj",
        ".cljs",
        ".conf",
        ".cpp",
        ".cs",
        ".css",
        ".cxx",
        ".dart",
        ".edn",
        ".env",
        ".erl",
        ".ex",
        ".exs",
        ".fish",
        ".go",
        ".gradle",
        ".graphql",
        ".groovy",
        ".h",
        ".hcl",
        ".hrl",
        ".htm",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".kt",
        ".kts",
        ".less",
        ".lua",
        ".md",
        ".mdx",
        ".nix",
        ".php",
        ".pl",
        ".properties",
        ".proto",
        ".ps1",
        ".py",
        ".r",
        ".rb",
        ".rs",
        ".sass",
        ".scala",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".tf",
        ".tfvars",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vim",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
    _CODE_FILE_NAMES: ClassVar[set[str]] = {
        ".env.example",
        "dockerfile",
        "gemfile",
        "jenkinsfile",
        "makefile",
        "procfile",
        "rakefile",
    }
    _EXCLUDED_FILE_NAMES: ClassVar[set[str]] = {
        "cargo.lock",
        "composer.lock",
        "package-lock.json",
        "pipfile.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "yarn.lock",
    }

    def _get_requests_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=[
                "HEAD",
                "GET",
                "PUT",
                "DELETE",
                "OPTIONS",
                "TRACE",
                "POST",
            ],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.verify = certifi.where()
        return session

    def _normalize_url(self, value: Any, default: str, name: str) -> str:
        if value is None or value == "":
            return default
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError(f"{name} must start with http:// or https://")
        return normalized

    def _get_api_base_url(self) -> str:
        return self._normalize_url(
            self.runtime.credentials.get("cnb_api_base_url"),
            self._DEFAULT_API_BASE_URL,
            "CNB API URL",
        )

    def _get_web_url(self) -> str:
        return self._normalize_url(
            self.runtime.credentials.get("cnb_web_url"),
            self._DEFAULT_WEB_URL,
            "CNB URL",
        )

    def _get_headers(self) -> dict[str, str]:
        access_token = self.runtime.credentials.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("CNB access token is required")
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token.strip()}",
            "User-Agent": "Dify-CNB-Datasource",
        }

    def _safe_json_response(self, response: requests.Response) -> Any:
        if response.status_code >= 400:
            self._raise_api_error(response)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(f"Invalid JSON response from CNB: {exc}") from exc

    def _raise_api_error(self, response: requests.Response) -> None:
        detail = response.text[:1000]
        if response.status_code == 401:
            raise CNBAPIError(401, f"Invalid CNB access token: {detail}")
        if response.status_code == 403:
            raise CNBAPIError(403, f"CNB access forbidden: {detail}")
        if response.status_code == 404:
            raise CNBAPIError(404, f"CNB resource not found: {detail}")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise CNBAPIError(
                429,
                f"CNB API rate limit exceeded; retry after {retry_after} seconds",
            )
        raise CNBAPIError(
            response.status_code,
            f"CNB API error: {response.status_code} - {detail}",
        )

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        url = f"{self._get_api_base_url()}{path}"
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid CNB API URL: {url}")
        try:
            response = self._get_requests_session().request(
                method,
                url,
                headers=self._get_headers(),
                params=dict(params or {}),
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Network error while accessing CNB: {exc}") from exc
        return self._safe_json_response(response)

    def _encode_repo_path(self, repo_path: str) -> str:
        if not isinstance(repo_path, str):
            raise TypeError("CNB repository path must be a string")
        normalized = repo_path.strip().strip("/")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2 or any(part in {".", ".."} for part in parts):
            raise ValueError(
                "CNB repository path must use the format namespace/repository"
            )
        return "/".join(quote(part, safe="") for part in parts)

    def _encode_file_path(self, file_path: str) -> str:
        if not isinstance(file_path, str):
            raise TypeError("CNB file path must be a string")
        normalized = file_path.strip().strip("/")
        parts = [part for part in normalized.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("Invalid CNB file path")
        return "/".join(quote(part, safe="") for part in parts)

    def _normalize_ref(self, value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError("CNB ref must be a string")
        ref = value.strip()
        if not ref:
            return ""
        if "://" in ref:
            parsed = urlparse(ref)
            host = (parsed.hostname or "").casefold()
            if host not in {"cnb.cool", "www.cnb.cool"}:
                raise ValueError(
                    "CNB ref URL must use cnb.cool, for example "
                    "https://cnb.cool/group/repository/-/tree/develop"
                )
            path = unquote(parsed.path)
            for marker in ("/-/tree/", "/-/blob/", "/-/commit/"):
                if marker in path:
                    ref = path.split(marker, 1)[1].split("/", 1)[0]
                    break
            else:
                raise ValueError("CNB ref URL must point to a tree, blob, or commit")
        return ref.removeprefix("refs/heads/").removeprefix("refs/tags/").strip()

    def _normalize_ref_type(self, value: Any) -> str:
        if value is None or value == "":
            return "auto"
        if not isinstance(value, str):
            raise TypeError("CNB ref type must be a string")
        ref_type = value.strip().casefold()
        if ref_type not in {"auto", "branch", "tag", "commit"}:
            raise ValueError("CNB ref type must be one of auto, branch, tag, or commit")
        return ref_type

    def _extract_commit_sha(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        commit = payload.get("commit")
        if isinstance(commit, dict) and isinstance(commit.get("sha"), str):
            return commit["sha"]
        if isinstance(payload.get("sha"), str):
            return payload["sha"]
        if payload.get("target_type") == "commit" and isinstance(
            payload.get("target"), str
        ):
            return payload["target"]
        return None

    def _resolve_ref(self, repo_path: str, ref: str, ref_type: str) -> str:
        if not ref or ref_type == "auto":
            return ref

        encoded_repo = self._encode_repo_path(repo_path)
        encoded_ref = quote(ref, safe="")
        if ref_type == "branch":
            payload = self._request(
                "GET",
                f"/{encoded_repo}/-/git/branches/{encoded_ref}",
            )
        elif ref_type == "tag":
            payload = self._request(
                "GET",
                f"/{encoded_repo}/-/git/tags/{encoded_ref}",
            )
        else:
            payload = self._request(
                "GET",
                f"/{encoded_repo}/-/git/commits/{encoded_ref}",
            )

        commit_sha = self._extract_commit_sha(payload)
        if not commit_sha:
            raise CNBAPIError(
                404,
                f"Unable to resolve {ref_type} '{ref}' in {repo_path}",
            )
        return commit_sha

    def _encode_ref(self, ref: str) -> str:
        if not ref:
            return ""
        return base64.urlsafe_b64encode(ref.encode("utf-8")).decode("ascii").rstrip("=")

    def _decode_ref(self, encoded_ref: str) -> str:
        if not encoded_ref:
            return ""
        padding = "=" * (-len(encoded_ref) % 4)
        try:
            return base64.urlsafe_b64decode(encoded_ref + padding).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("Invalid encoded CNB ref") from exc

    def _make_project_page_id(self, repo_path: str, ref: str = "") -> str:
        if not ref:
            return f"project:{repo_path}"
        return f"project:{repo_path}|{self._encode_ref(ref)}"

    def _make_file_page_id(self, repo_path: str, file_path: str, ref: str = "") -> str:
        if not ref:
            return f"file:{repo_path}:{file_path}"
        return f"file:{repo_path}|{self._encode_ref(ref)}:{file_path}"

    def _parse_project_page_id(self, page_id: str) -> tuple[str, str]:
        repo_token = page_id[len("project:") :]
        return self._parse_repo_ref_token(repo_token)

    def _parse_repo_ref_token(self, token: str) -> tuple[str, str]:
        repo_path, separator, encoded_ref = token.partition("|")
        if not separator:
            return repo_path, ""
        return repo_path, self._decode_ref(encoded_ref)

    def _get_user(self) -> dict[str, Any]:
        user = self._request("GET", "/user")
        if not isinstance(user, dict):
            raise TypeError("CNB user response is not a JSON object")
        return user

    def _get_repositories(
        self,
        max_repos: int,
        repository_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if repository_paths:
            repositories = []
            for repo_path in repository_paths:
                repositories.append(
                    {
                        "path": repo_path,
                        "name": repo_path.rsplit("/", 1)[-1],
                    }
                )
            return repositories

        repositories = self._request(
            "GET",
            "/user/repos",
            {
                "page": 1,
                "page_size": max_repos,
                "role": "Guest",
                "order_by": "last_updated_at",
                "desc": "true",
            },
        )
        if not isinstance(repositories, list):
            raise TypeError("CNB repository response is not a JSON array")
        return [repo for repo in repositories if isinstance(repo, dict)]

    def _parse_repository_paths(self, value: Any) -> list[str]:
        if not isinstance(value, str) or not value.strip():
            return []
        paths: list[str] = []
        for item in value.replace("\r", "\n").replace(",", "\n").split("\n"):
            raw = item.strip()
            if not raw:
                continue
            if "://" in raw:
                parsed = urlparse(raw)
                host = (parsed.hostname or "").casefold()
                if host not in {"cnb.cool", "www.cnb.cool", "api.cnb.cool"}:
                    raise ValueError(
                        "CNB repository URL must use cnb.cool, for example "
                        "https://cnb.cool/group/repository"
                    )
                normalized = unquote(parsed.path)
            else:
                normalized = unquote(raw)
                if normalized.casefold().startswith("cnb.cool/"):
                    normalized = normalized[len("cnb.cool/") :]

            normalized = normalized.split("?", 1)[0].split("#", 1)[0].strip("/")
            if "/-/" in normalized:
                normalized = normalized.split("/-/", 1)[0]
            if normalized.casefold().endswith(".git"):
                normalized = normalized[:-4].strip("/")
            if not normalized or normalized in paths:
                continue
            parts = [part for part in normalized.split("/") if part]
            if len(parts) < 2 or any(part in {".", ".."} for part in parts):
                raise ValueError(
                    "CNB repository paths must use a full path such as "
                    "group/repository or https://cnb.cool/group/repository"
                )
            paths.append("/".join(parts))
        return paths

    def _is_code_file(self, file_path: str) -> bool:
        file_name = file_path.rsplit("/", 1)[-1].casefold()
        if file_name in self._README_CANDIDATES:
            return False
        if file_name in self._EXCLUDED_FILE_NAMES:
            return False
        if file_name.endswith((".min.js", ".min.css", ".map")):
            return False
        if file_name in self._CODE_FILE_NAMES:
            return True
        dot_index = file_name.rfind(".")
        if dot_index < 0:
            return False
        return file_name[dot_index:] in self._CODE_FILE_EXTENSIONS

    def _list_code_files(
        self, repo_path: str, max_files: int, ref: str = ""
    ) -> list[str]:
        if max_files <= 0:
            return []

        encoded_repo = self._encode_repo_path(repo_path)
        pending_directories = [""]
        files: list[str] = []
        visited_directories: set[str] = set()

        while pending_directories and len(files) < max_files:
            if len(visited_directories) >= self._MAX_TREE_DIRECTORIES:
                break

            directory = pending_directories.pop(0)
            if directory in visited_directories:
                continue
            visited_directories.add(directory)

            if directory:
                path = (
                    f"/{encoded_repo}/-/git/contents/"
                    f"{self._encode_file_path(directory)}"
                )
            else:
                path = f"/{encoded_repo}/-/git/contents"

            try:
                payload = self._request(
                    "GET",
                    path,
                    {"ref": ref} if ref else None,
                )
            except CNBAPIError:
                continue
            if not isinstance(payload, dict):
                continue
            entries = payload.get("entries")
            if not isinstance(entries, list):
                continue

            for entry in entries:
                if len(files) >= max_files:
                    break
                if not isinstance(entry, dict):
                    continue
                entry_type = entry.get("type")
                entry_path = entry.get("path")
                if not isinstance(entry_path, str) or not entry_path:
                    continue

                if entry_type == "tree":
                    depth = entry_path.count("/")
                    if (
                        depth <= self._MAX_TREE_DEPTH
                        and entry_path.rsplit("/", 1)[-1]
                        not in self._EXCLUDED_DIRECTORIES
                    ):
                        pending_directories.append(entry_path)
                elif entry_type == "blob" and self._is_code_file(entry_path):
                    files.append(entry_path)

        return files

    def _find_readme_path(
        self,
        repo_path: str,
        ref: str = "",
        raise_on_error: bool = False,
    ) -> str | None:
        try:
            root = self._request(
                "GET",
                f"/{self._encode_repo_path(repo_path)}/-/git/contents",
                {"ref": ref} if ref else None,
            )
        except CNBAPIError as exc:
            if raise_on_error:
                raise CNBAPIError(
                    exc.status_code,
                    f"{exc} (repository={repo_path}, ref={ref or 'default branch'})",
                ) from exc
            return None
        if not isinstance(root, dict):
            return None
        entries = root.get("entries")
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            if name.casefold() in self._README_CANDIDATES:
                path = entry.get("path") or name
                if isinstance(path, str) and entry.get("type") == "blob":
                    return path
        return None

    def _get_pages(
        self, datasource_parameters: Mapping[str, Any]
    ) -> DatasourceGetPagesResponse:
        self._get_headers()

        max_repos = self._bounded_int(
            datasource_parameters.get("max_repos"),
            20,
            1,
            100,
            zero_means_default=True,
        )
        issues_per_repo = self._bounded_int(
            datasource_parameters.get("issues_per_repo"), 5, 0, 50
        )
        pulls_per_repo = self._bounded_int(
            datasource_parameters.get("pulls_per_repo"), 5, 0, 50
        )
        max_files_per_repo = self._bounded_int(
            datasource_parameters.get("max_files_per_repo"), 100, 0, 1000
        )
        include_code_files = self._bool_value(
            datasource_parameters.get("include_code_files"),
            True,
        )
        repository_paths = self._parse_repository_paths(
            datasource_parameters.get("repository_paths")
        )
        if not repository_paths:
            repository_paths = self._parse_repository_paths(
                self.runtime.credentials.get("repository_path")
            )
        ref = self._normalize_ref(datasource_parameters.get("ref"))
        ref_type = self._normalize_ref_type(datasource_parameters.get("ref_type"))

        repository_scoped = bool(repository_paths)
        user = {} if repository_scoped else self._get_user()
        repositories = self._get_repositories(max_repos, repository_paths)
        pages: list[dict[str, Any]] = []

        for repo in repositories:
            repo_path = repo.get("path")
            if not isinstance(repo_path, str) or not repo_path:
                continue

            repo_name = str(repo.get("name") or repo_path.rsplit("/", 1)[-1])
            last_updated = self._first_string(
                repo.get("last_updated_at"),
                repo.get("updated_at"),
                repo.get("created_at"),
            )
            ref_label = ref or "default branch"
            actual_ref = ref
            ref_available = True
            try:
                actual_ref = self._resolve_ref(repo_path, ref, ref_type)
                readme_path = self._find_readme_path(
                    repo_path,
                    actual_ref,
                    raise_on_error=bool(actual_ref),
                )
            except CNBAPIError:
                readme_path = None
                ref_available = False
            project_page_id = self._make_project_page_id(repo_path, actual_ref)
            project_page_name = (
                f"{repo_name} ({ref})"
                if ref_available and ref
                else f"{repo_name} ({ref} unavailable)"
                if ref
                else f"{repo_name} ({ref_label})"
            )
            pages.append(
                {
                    "page_id": project_page_id,
                    "page_name": project_page_name,
                    "last_edited_time": last_updated,
                    "type": "project",
                }
            )

            if ref_available and readme_path:
                pages.append(
                    {
                        "page_id": self._make_file_page_id(
                            repo_path,
                            readme_path,
                            actual_ref,
                        ),
                        "page_name": f"{repo_name} ({ref_label}) - {readme_path}",
                        "last_edited_time": last_updated,
                        "type": "file",
                        "parent_id": project_page_id,
                    }
                )

            if ref_available and include_code_files and max_files_per_repo > 0:
                for code_path in self._list_code_files(
                    repo_path,
                    max_files_per_repo,
                    actual_ref,
                ):
                    if code_path == readme_path:
                        continue
                    pages.append(
                        {
                            "page_id": self._make_file_page_id(
                                repo_path,
                                code_path,
                                actual_ref,
                            ),
                            "page_name": f"{repo_name} ({ref_label}) - {code_path}",
                            "last_edited_time": last_updated,
                            "type": "file",
                            "parent_id": project_page_id,
                        }
                    )

            if issues_per_repo > 0:
                try:
                    issues = self._request(
                        "GET",
                        f"/{self._encode_repo_path(repo_path)}/-/issues",
                        {
                            "state": "all",
                            "page": 1,
                            "page_size": issues_per_repo,
                            "order_by": "-updated_at",
                        },
                    )
                except CNBAPIError:
                    issues = []
                if isinstance(issues, list):
                    for issue in issues:
                        if not isinstance(issue, dict):
                            continue
                        number = issue.get("number")
                        title = str(issue.get("title") or "Untitled")
                        if number is None:
                            continue
                        pages.append(
                            {
                                "page_id": f"issue:{repo_path}:{number}",
                                "page_name": f"Issue #{number}: {title}",
                                "last_edited_time": self._first_string(
                                    issue.get("updated_at"),
                                    issue.get("last_acted_at"),
                                    issue.get("created_at"),
                                ),
                                "type": "issue",
                                "parent_id": project_page_id,
                            }
                        )

            if pulls_per_repo > 0:
                try:
                    pulls = self._request(
                        "GET",
                        f"/{self._encode_repo_path(repo_path)}/-/pulls",
                        {
                            "state": "all",
                            "page": 1,
                            "page_size": pulls_per_repo,
                            "order_by": "-updated_at",
                        },
                    )
                except CNBAPIError:
                    pulls = []
                if isinstance(pulls, list):
                    for pull in pulls:
                        if not isinstance(pull, dict):
                            continue
                        number = pull.get("number")
                        title = str(pull.get("title") or "Untitled")
                        if number is None:
                            continue
                        pages.append(
                            {
                                "page_id": f"pull:{repo_path}:{number}",
                                "page_name": f"PR #{number}: {title}",
                                "last_edited_time": self._first_string(
                                    pull.get("updated_at"),
                                    pull.get("last_acted_at"),
                                    pull.get("created_at"),
                                ),
                                "type": "pull",
                                "parent_id": project_page_id,
                            }
                        )

        workspace_name = (
            f"{user.get('nickname') or user.get('username') or 'CNB'}'s CNB"
            if user
            else "CNB Repositories"
        )
        workspace_id = (
            str(user.get("id") or user.get("username") or "cnb")
            if user
            else "|".join(repository_paths)
        )
        workspace_icon = self._first_string(user.get("avatar"))

        online_document_info = OnlineDocumentInfo(
            workspace_name=workspace_name,
            workspace_icon=workspace_icon,
            workspace_id=workspace_id,
            pages=pages,
            total=len(pages),
        )
        return DatasourceGetPagesResponse(result=[online_document_info])

    def _get_content(
        self, page: GetOnlineDocumentPageContentRequest
    ) -> Generator[DatasourceMessage, None, None]:
        self._get_headers()
        page_id = page.page_id
        if page_id.startswith("project:"):
            yield from self._get_project_content(page_id)
        elif page_id.startswith("file:"):
            yield from self._get_file_content(page_id)
        elif page_id.startswith("issue:"):
            yield from self._get_issue_content(page_id)
        elif page_id.startswith("pull:"):
            yield from self._get_pull_content(page_id)
        else:
            raise ValueError(f"Unsupported CNB page type: {page_id}")

    def _get_project_content(
        self, page_id: str
    ) -> Generator[DatasourceMessage, None, None]:
        repo_path, ref = self._parse_project_page_id(page_id)
        repo = self._request("GET", f"/{self._encode_repo_path(repo_path)}")
        if not isinstance(repo, dict):
            raise TypeError("CNB repository response is not a JSON object")

        path = str(repo.get("path") or repo_path)
        content = f"# {repo.get('name') or path}\n\n"
        content += f"**Repository:** {path}\n"
        content += f"**Ref:** {ref or 'default branch'}\n"
        content += f"**Description:** {repo.get('description') or 'No description'}\n"
        content += f"**Visibility:** {repo.get('visibility_level') or 'unknown'}\n"
        content += f"**Status:** {repo.get('status') or 'unknown'}\n"
        content += f"**Language:** {self._format_languages(repo)}\n"
        content += f"**License:** {repo.get('license') or 'Not specified'}\n"
        content += f"**Stars:** {repo.get('star_count', 0)}\n"
        content += f"**Forks:** {repo.get('fork_count', 0)}\n"
        content += f"**Open Issues:** {repo.get('open_issue_count', 0)}\n"
        content += f"**Open Pull Requests:** {repo.get('open_pull_request_count', 0)}\n"
        content += f"**Created:** {repo.get('created_at') or ''}\n"
        content += f"**Last Updated:** {repo.get('last_updated_at') or ''}\n"
        web_url = repo.get("web_url")
        if not isinstance(web_url, str) or not web_url.rstrip("/").endswith(path):
            web_url = self._repo_web_url(path)
        content += f"**URL:** {web_url}\n\n"

        topics = repo.get("topics")
        if topics:
            content += f"**Topics:** {topics}\n\n"

        readme_path = self._find_readme_path(path, ref)
        if readme_path:
            try:
                readme = self._read_file(path, readme_path, ref)
                content += f"## {readme_path}\n\n{readme}"
            except (CNBAPIError, ValueError):
                content += "## README\n\nUnable to read the README file."
        else:
            content += "## README\n\nNo README file found."

        yield self.create_variable_message("content", content)
        yield self.create_variable_message("page_id", page_id)
        yield self.create_variable_message("title", str(repo.get("name") or path))
        yield self.create_variable_message("project", path)
        yield self.create_variable_message("ref", ref)
        yield self.create_variable_message("type", "project")

    def _get_file_content(
        self, page_id: str
    ) -> Generator[DatasourceMessage, None, None]:
        parts = page_id.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid CNB file page id: {page_id}")
        _, repo_ref, file_path = parts
        repo_path, ref = self._parse_repo_ref_token(repo_ref)
        content = self._read_file(repo_path, file_path, ref)
        file_name = file_path.rsplit("/", 1)[-1]

        yield self.create_variable_message("content", content)
        yield self.create_variable_message("page_id", page_id)
        yield self.create_variable_message("title", file_name)
        yield self.create_variable_message("project", repo_path)
        yield self.create_variable_message("file_path", file_path)
        yield self.create_variable_message("ref", ref)
        yield self.create_variable_message("type", "file")

    def _read_file(self, repo_path: str, file_path: str, ref: str = "") -> str:
        encoded_repo = self._encode_repo_path(repo_path)
        encoded_file = self._encode_file_path(file_path)
        payload = self._request(
            "GET",
            f"/{encoded_repo}/-/git/contents/{encoded_file}",
            {"ref": ref} if ref else None,
        )
        if not isinstance(payload, dict):
            raise TypeError("CNB file response is not a JSON object")

        content_type = payload.get("type")
        if content_type == "tree":
            entries = payload.get("entries")
            if not isinstance(entries, list):
                return "Directory is empty."
            lines = [f"# {payload.get('path') or file_path}", ""]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry_type = entry.get("type") or "unknown"
                entry_path = entry.get("path") or entry.get("name") or ""
                lines.append(f"- `{entry_path}` ({entry_type})")
            return "\n".join(lines)

        if content_type == "lfs":
            return (
                f"LFS object: {payload.get('lfs_oid') or payload.get('sha') or 'unknown'}\n\n"
                f"Size: {payload.get('lfs_size') or payload.get('size') or 'unknown'} bytes\n\n"
                f"Download URL: {payload.get('lfs_download_url') or 'unavailable'}"
            )

        encoded_content = payload.get("content")
        if payload.get("encoding") == "base64":
            if not isinstance(encoded_content, str):
                raise ValueError("CNB file response is missing base64 content")
            try:
                return base64.b64decode(encoded_content).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise ValueError(f"Failed to decode CNB file content: {exc}") from exc

        if encoded_content is None:
            return ""
        return str(encoded_content)

    def _get_issue_content(
        self, page_id: str
    ) -> Generator[DatasourceMessage, None, None]:
        parts = page_id.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid CNB issue page id: {page_id}")
        _, repo_path, number = parts
        encoded_repo = self._encode_repo_path(repo_path)
        issue = self._request(
            "GET", f"/{encoded_repo}/-/issues/{quote(number, safe='')}"
        )
        if not isinstance(issue, dict):
            raise TypeError("CNB issue response is not a JSON object")

        title = str(issue.get("title") or "Untitled")
        content = f"# Issue #{issue.get('number') or number}: {title}\n\n"
        content += f"**Repository:** {repo_path}\n"
        content += f"**Author:** {self._format_user(issue.get('author'))}\n"
        content += f"**State:** {issue.get('state') or 'unknown'}\n"
        content += f"**Priority:** {issue.get('priority') or 'none'}\n"
        content += f"**Assignees:** {self._format_users(issue.get('assignees'))}\n"
        content += f"**Labels:** {self._format_labels(issue.get('labels'))}\n"
        content += f"**Created:** {issue.get('created_at') or ''}\n"
        content += f"**Updated:** {issue.get('updated_at') or ''}\n"
        content += f"**URL:** {self._issue_web_url(repo_path, issue.get('number') or number)}\n\n"

        properties = issue.get("properties")
        if isinstance(properties, list) and properties:
            content += "## Properties\n\n"
            for prop in properties:
                if isinstance(prop, dict):
                    name = prop.get("name") or prop.get("key")
                    content += f"- **{name}:** {prop.get('value') or ''}\n"
            content += "\n"

        if issue.get("body"):
            content += f"## Description\n\n{issue['body']}\n\n"

        comments = self._get_comments(
            f"/{encoded_repo}/-/issues/{quote(str(number), safe='')}/comments"
        )
        if comments:
            content += "## Comments\n\n"
            for comment in comments:
                content += self._format_comment(comment)

        yield self.create_variable_message("content", content)
        yield self.create_variable_message("page_id", page_id)
        yield self.create_variable_message(
            "title", f"Issue #{issue.get('number') or number}: {title}"
        )
        yield self.create_variable_message("project", repo_path)
        yield self.create_variable_message(
            "issue_number", str(issue.get("number") or number)
        )
        yield self.create_variable_message("type", "issue")

    def _get_pull_content(
        self, page_id: str
    ) -> Generator[DatasourceMessage, None, None]:
        parts = page_id.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid CNB pull page id: {page_id}")
        _, repo_path, number = parts
        encoded_repo = self._encode_repo_path(repo_path)
        pull = self._request("GET", f"/{encoded_repo}/-/pulls/{quote(number, safe='')}")
        if not isinstance(pull, dict):
            raise TypeError("CNB pull request response is not a JSON object")

        title = str(pull.get("title") or "Untitled")
        content = f"# Pull Request #{pull.get('number') or number}: {title}\n\n"
        content += f"**Repository:** {repo_path}\n"
        content += f"**Author:** {self._format_user(pull.get('author'))}\n"
        content += f"**State:** {pull.get('state') or 'unknown'}\n"
        content += f"**Draft:** {pull.get('is_wip', False)}\n"
        content += f"**Source Branch:** {self._format_ref(pull.get('head'))}\n"
        content += f"**Target Branch:** {self._format_ref(pull.get('base'))}\n"
        content += f"**Mergeable State:** {pull.get('mergeable_state') or 'unknown'}\n"
        content += f"**Labels:** {self._format_labels(pull.get('labels'))}\n"
        content += f"**Reviewers:** {self._format_reviewers(pull.get('reviewers'))}\n"
        content += f"**Created:** {pull.get('created_at') or ''}\n"
        content += f"**Updated:** {pull.get('updated_at') or ''}\n"
        content += f"**URL:** {self._pull_web_url(repo_path, pull.get('number') or number)}\n\n"

        if pull.get("body"):
            content += f"## Description\n\n{pull['body']}\n\n"

        comments = self._get_comments(
            f"/{encoded_repo}/-/pulls/{quote(str(number), safe='')}/comments"
        )
        if comments:
            content += "## Comments\n\n"
            for comment in comments:
                content += self._format_comment(comment)

        yield self.create_variable_message("content", content)
        yield self.create_variable_message("page_id", page_id)
        yield self.create_variable_message(
            "title", f"PR #{pull.get('number') or number}: {title}"
        )
        yield self.create_variable_message("project", repo_path)
        yield self.create_variable_message(
            "pull_number", str(pull.get("number") or number)
        )
        yield self.create_variable_message("type", "pull")

    def _get_comments(self, path: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for page in range(1, 6):
            payload = self._request(
                "GET",
                path,
                {"page": page, "page_size": 100},
            )
            if not isinstance(payload, list):
                break
            comments.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 100:
                break
        return comments

    def _format_comment(self, comment: Mapping[str, Any]) -> str:
        author = self._format_user(comment.get("author"))
        created_at = comment.get("created_at") or comment.get("updated_at") or ""
        body = comment.get("body") or ""
        return f"### {author} - {created_at}\n\n{body}\n\n"

    def _format_user(self, user: Any) -> str:
        if not isinstance(user, dict):
            return "unknown"
        return str(
            user.get("nickname")
            or user.get("username")
            or user.get("name")
            or user.get("user_name")
            or "unknown"
        )

    def _format_users(self, users: Any) -> str:
        if not isinstance(users, list):
            return "none"
        names = [self._format_user(user) for user in users if isinstance(user, dict)]
        return ", ".join(name for name in names if name != "unknown") or "none"

    def _format_labels(self, labels: Any) -> str:
        if not isinstance(labels, list):
            return "none"
        names = []
        for label in labels:
            if isinstance(label, dict):
                name = label.get("name")
            else:
                name = label
            if name:
                names.append(str(name))
        return ", ".join(names) or "none"

    def _format_reviewers(self, reviewers: Any) -> str:
        if not isinstance(reviewers, list):
            return "none"
        formatted = []
        for reviewer in reviewers:
            if not isinstance(reviewer, dict):
                continue
            name = self._format_user(reviewer.get("user"))
            state = reviewer.get("review_state") or reviewer.get("state")
            formatted.append(f"{name} ({state or 'pending'})")
        return ", ".join(formatted) or "none"

    def _format_ref(self, value: Any) -> str:
        if not isinstance(value, dict):
            return "unknown"
        ref = str(value.get("ref") or "unknown")
        return ref.removeprefix("refs/heads/").removeprefix("refs/tags/")

    def _format_languages(self, repo: Mapping[str, Any]) -> str:
        languages = repo.get("languages")
        if isinstance(languages, dict) and languages:
            language_name = languages.get("language") or languages.get("name")
            if language_name:
                return str(language_name)
            return ", ".join(str(name) for name in languages)
        if isinstance(languages, str) and languages:
            return languages
        return str(repo.get("language") or "unknown")

    def _repo_web_url(self, repo_path: str) -> str:
        return f"{self._get_web_url()}/{repo_path.strip('/')}"

    def _issue_web_url(self, repo_path: str, number: Any) -> str:
        return f"{self._repo_web_url(repo_path)}/-/issues/{number}"

    def _pull_web_url(self, repo_path: str, number: Any) -> str:
        return f"{self._repo_web_url(repo_path)}/-/pulls/{number}"

    def _first_string(self, *values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value:
                return value
        return ""

    def _bounded_int(
        self,
        value: Any,
        default: int,
        minimum: int,
        maximum: int,
        zero_means_default: bool = False,
    ) -> int:
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = default
        if zero_means_default and result == 0:
            result = default
        return max(minimum, min(maximum, result))

    def _bool_value(self, value: Any, default: bool) -> bool:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default
