import typing

import httpware

from semvertag import _link_pagination
from semvertag._errors import ProviderAPIError


_PageT = typing.TypeVar("_PageT")
_ItemT = typing.TypeVar("_ItemT")


def collect_link_pages(  # noqa: PLR0913
    http: httpware.Client,
    *,
    url: str,
    params: dict[str, typing.Any],
    response_model: type[_PageT],
    extract: typing.Callable[[_PageT], typing.Iterable[_ItemT]],
    translate: typing.Callable[[httpware.ClientError], Exception],
    endpoint: str,
    max_pages: int,
    cross_origin_message: str,
    pagination_cap_message: str,
) -> list[_ItemT]:
    """
    Walk RFC 8288 Link-header pages, accumulating extracted items.

    Shared by every forge whose list endpoints paginate via Link headers
    (GitHub, GitLab both do, because it is a spec — not a coincidence). The
    forge-specific parts are passed in as data: the response model and its
    `extract` projection, the error `translate` callable, and the two messages
    that name the forge. The loop, the same-origin credential guard, and the
    page cap live here, once.
    """
    items: list[_ItemT] = []
    current_url: str = url
    current_params: dict[str, typing.Any] | None = params
    for _ in range(max_pages):
        try:
            response, page = http.get_with_response(current_url, params=current_params, response_model=response_model)
        except httpware.ClientError as exc:
            raise translate(exc) from exc
        items.extend(extract(page))
        next_url = _link_pagination.next_page_url(response, current_url=str(response.request.url))
        if next_url is None:
            return items
        if not _link_pagination.same_origin(next_url, endpoint):
            raise ProviderAPIError(cross_origin_message)
        current_url, current_params = next_url, None
    raise ProviderAPIError(pagination_cap_message)
