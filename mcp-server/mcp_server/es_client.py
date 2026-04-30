"""ES 客户端封装，支持直连 Elasticsearch 和通过 Kibana Console Proxy 两种模式。"""

import logging
import time
from typing import Any, Optional

from mcp_server.config import ElkConfig

logger = logging.getLogger(__name__)

MAX_RETRIES = 1
RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


class ElkClient:
    """统一的 ES 操作客户端，根据 config.mode 自动选择连接方式。"""
    def __init__(self, config: ElkConfig):
        self._config = config
        if config.mode == "elasticsearch":
            self._init_es(config)
        elif config.mode == "kibana":
            self._init_kibana(config)
        else:
            raise ValueError(f"Invalid mode: {config.mode!r}")

    def _init_es(self, config: ElkConfig) -> None:
        from elasticsearch import Elasticsearch

        self._es = Elasticsearch(
            config.host,
            basic_auth=(config.username, config.password),
            verify_certs=config.verify_certs,
            request_timeout=config.timeout_seconds,
        )
        self._mode = "elasticsearch"

    def _init_kibana(self, config: ElkConfig) -> None:
        import httpx

        self._http = httpx.Client(
            base_url=config.host,
            auth=(config.username, config.password),
            headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
            verify=config.verify_certs,
            timeout=config.timeout_seconds,
        )
        self._mode = "kibana"
        space = config.kibana_space.strip().strip("/")
        self._proxy_prefix = f"/s/{space}" if space else ""

    def _kibana_request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        """通过 Kibana Console Proxy API 转发 ES 请求，失败自动重试一次。"""
        import httpx

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs = {"params": {"path": path, "method": method}}
                if body is not None:
                    kwargs["json"] = body
                resp = self._http.post(f"{self._proxy_prefix}/api/console/proxy", **kwargs)
                resp.raise_for_status()
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    logger.warning("Kibana request failed (attempt %d), retrying: %s", attempt + 1, exc)
                    time.sleep(1)
                else:
                    raise
            except httpx.HTTPStatusError:
                raise

    def cat_indices(self, pattern: str = "*") -> list[dict[str, Any]]:
        if self._mode == "elasticsearch":
            return self._es.cat.indices(index=pattern, format="json", h="index,docs.count,store.size")
        return self._kibana_request("GET", f"/_cat/indices/{pattern}?format=json&h=index,docs.count,store.size")

    def get_mapping(self, index: str) -> dict[str, Any]:
        if self._mode == "elasticsearch":
            return self._es.indices.get_mapping(index=index)
        return self._kibana_request("GET", f"/{index}/_mapping")

    def count(self, index: str, body: Optional[dict] = None) -> int:
        if self._mode == "elasticsearch":
            result = self._es.count(index=index, body=body or {})
            return result["count"]
        result = self._kibana_request("POST", f"/{index}/_count", body or {})
        return result["count"]

    def search(
        self,
        index: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        if self._mode == "elasticsearch":
            return self._es.search(index=index, body=body)
        return self._kibana_request("POST", f"/{index}/_search", body)

    def close(self) -> None:
        if self._mode == "elasticsearch":
            self._es.close()
        else:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
