import base64
import time
import urllib.parse
from collections.abc import Mapping
from typing import Any

import certifi
import requests
from dify_plugin.errors.tool import (
    DatasourceOAuthError,
    ToolProviderCredentialValidationError,
)
from dify_plugin.interfaces.datasource import (
    DatasourceOAuthCredentials,
    DatasourceProvider,
)
from flask import Request
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class CNBDatasourceProvider(DatasourceProvider):
    _DEFAULT_API_BASE_URL = "https://api.cnb.cool"
    _DEFAULT_WEB_URL = "https://cnb.cool"

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
            raise ToolProviderCredentialValidationError(f"{name} must be a string")
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ToolProviderCredentialValidationError(
                f"{name} must start with http:// or https://"
            )
        return normalized

    def _normalize_repository_path(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        raw = value.strip()
        if "://" in raw:
            parsed = urllib.parse.urlparse(raw)
            host = (parsed.hostname or "").casefold()
            if host not in {"cnb.cool", "www.cnb.cool", "api.cnb.cool"}:
                raise ToolProviderCredentialValidationError(
                    "CNB repository URL must use cnb.cool"
                )
            raw = urllib.parse.unquote(parsed.path)
        raw = raw.strip("/")
        if "/-/" in raw:
            raw = raw.split("/-/", 1)[0]
        if raw.casefold().endswith(".git"):
            raw = raw[:-4].strip("/")
        parts = [part for part in raw.split("/") if part]
        if len(parts) < 2 or any(part in {".", ".."} for part in parts):
            raise ToolProviderCredentialValidationError(
                "Repository path must use the format organization/group/repository"
            )
        return "/".join(parts)

    def _safe_json_response(self, response: requests.Response) -> Any:
        if response.status_code >= 400:
            raise DatasourceOAuthError(
                f"CNB API error: {response.status_code} - {response.text[:1000]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DatasourceOAuthError(
                f"Invalid JSON response from CNB: {exc}"
            ) from exc

    def _validate_credentials(self, credentials: Mapping[str, Any]) -> None:
        access_token = credentials.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ToolProviderCredentialValidationError("CNB access token is required")

        api_base_url = self._normalize_url(
            credentials.get("cnb_api_base_url"),
            self._DEFAULT_API_BASE_URL,
            "CNB API URL",
        )
        repository_path = self._normalize_repository_path(
            credentials.get("repository_path")
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token.strip()}",
            "User-Agent": "Dify-CNB-Datasource",
        }

        validation_urls = (
            [
                f"{api_base_url}/{repository_path}",
                f"{api_base_url}/{repository_path}/-/git/contents",
            ]
            if repository_path
            else [f"{api_base_url}/user"]
        )

        try:
            session = self._get_requests_session()
            for validation_url in validation_urls:
                response = session.get(validation_url, headers=headers, timeout=10)
                if response.status_code == 401:
                    raise ToolProviderCredentialValidationError(
                        "Invalid CNB access token"
                    )
                if response.status_code >= 400:
                    raise ToolProviderCredentialValidationError(
                        f"CNB API error: {response.status_code} - "
                        f"{response.text[:1000]}"
                    )
        except requests.exceptions.RequestException as exc:
            raise ToolProviderCredentialValidationError(
                f"Failed to connect to CNB: {exc}"
            ) from exc

    def _oauth_get_authorization_url(
        self, redirect_uri: str, system_credentials: Mapping[str, Any]
    ) -> str:
        web_url = self._normalize_url(
            system_credentials.get("cnb_web_url"),
            self._DEFAULT_WEB_URL,
            "CNB URL",
        )
        params = {
            "client_id": system_credentials["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
        }
        return f"{web_url}/oauth2/auth?{urllib.parse.urlencode(params)}"

    def _basic_auth_header(
        self, system_credentials: Mapping[str, Any]
    ) -> dict[str, str]:
        credentials = (
            f"{system_credentials['client_id']}:{system_credentials['client_secret']}"
        )
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dify-CNB-Datasource",
        }

    def _get_user_info(self, api_base_url: str, access_token: str) -> dict[str, Any]:
        response = self._get_requests_session().get(
            f"{api_base_url}/user",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "Dify-CNB-Datasource",
            },
            timeout=15,
        )
        user = self._safe_json_response(response)
        if not isinstance(user, dict):
            raise DatasourceOAuthError("CNB user response is not a JSON object")
        return user

    def _oauth_get_credentials(
        self, redirect_uri: str, system_credentials: Mapping[str, Any], request: Request
    ) -> DatasourceOAuthCredentials:
        code = request.args.get("code")
        if not code:
            raise DatasourceOAuthError("No authorization code provided")

        web_url = self._normalize_url(
            system_credentials.get("cnb_web_url"),
            self._DEFAULT_WEB_URL,
            "CNB URL",
        )
        api_base_url = self._normalize_url(
            system_credentials.get("cnb_api_base_url"),
            self._DEFAULT_API_BASE_URL,
            "CNB API URL",
        )

        try:
            response = self._get_requests_session().post(
                f"{web_url}/oauth2/token",
                headers=self._basic_auth_header(system_credentials),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=20,
            )
            token_data = self._safe_json_response(response)
        except requests.exceptions.RequestException as exc:
            raise DatasourceOAuthError(
                f"Failed to exchange CNB authorization code: {exc}"
            ) from exc

        access_token = token_data.get("access_token")
        if not access_token:
            raise DatasourceOAuthError("CNB token response is missing access_token")

        user = self._get_user_info(api_base_url, access_token)
        expires_in = int(token_data.get("expires_in", 28800))

        return DatasourceOAuthCredentials(
            name=user.get("nickname") or user.get("username"),
            avatar_url=user.get("avatar"),
            expires_at=int(time.time()) + expires_in,
            credentials={
                "access_token": access_token,
                "refresh_token": token_data.get("refresh_token"),
                "token_type": token_data.get("token_type", "bearer"),
                "cnb_api_base_url": api_base_url,
                "cnb_web_url": web_url,
                "user_login": user.get("username"),
            },
        )

    def _oauth_refresh_credentials(
        self,
        redirect_uri: str,
        system_credentials: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> DatasourceOAuthCredentials:
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise DatasourceOAuthError(
                "CNB refresh token is unavailable. Please authorize again."
            )

        web_url = self._normalize_url(
            credentials.get("cnb_web_url") or system_credentials.get("cnb_web_url"),
            self._DEFAULT_WEB_URL,
            "CNB URL",
        )
        api_base_url = self._normalize_url(
            credentials.get("cnb_api_base_url")
            or system_credentials.get("cnb_api_base_url"),
            self._DEFAULT_API_BASE_URL,
            "CNB API URL",
        )

        try:
            response = self._get_requests_session().post(
                f"{web_url}/oauth2/token",
                headers=self._basic_auth_header(system_credentials),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                timeout=20,
            )
            token_data = self._safe_json_response(response)
        except requests.exceptions.RequestException as exc:
            raise DatasourceOAuthError(f"Failed to refresh CNB token: {exc}") from exc

        access_token = token_data.get("access_token")
        if not access_token:
            raise DatasourceOAuthError("CNB refresh response is missing access_token")

        user = self._get_user_info(api_base_url, access_token)
        expires_in = int(token_data.get("expires_in", 28800))
        new_refresh_token = token_data.get("refresh_token", refresh_token)

        return DatasourceOAuthCredentials(
            name=user.get("nickname") or user.get("username"),
            avatar_url=user.get("avatar"),
            expires_at=int(time.time()) + expires_in,
            credentials={
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": token_data.get("token_type", "bearer"),
                "cnb_api_base_url": api_base_url,
                "cnb_web_url": web_url,
                "user_login": user.get("username"),
            },
        )
