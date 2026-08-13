"""Provider-isolated image generation adapters."""

import asyncio
import base64
import json
import struct
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx

ProviderStatusFamily = Literal["http_4xx", "http_5xx"]
ProviderOperation = Literal["reference_upload", "task_create", "task_poll", "result_download"]
DiagnosticCaptureStatus = Literal["not_attempted", "captured", "failed"]
DiagnosticImageMediaType = Literal["image/jpeg", "image/png"]

_MAX_DIAGNOSTIC_IMAGE_BYTES = 12 * 1024 * 1024
_PROVIDER_CONNECT_TIMEOUT_SECONDS = 10.0
_PROVIDER_WRITE_TIMEOUT_SECONDS = 30.0
_PROVIDER_READ_TIMEOUT_SECONDS = 120.0
_PROVIDER_POOL_TIMEOUT_SECONDS = 10.0
_KIE_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"
_KIE_CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
_KIE_TASK_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
_KIE_TEXT_TO_IMAGE_MODEL = "gpt-image-2-text-to-image"
_KIE_IMAGE_TO_IMAGE_MODEL = "gpt-image-2-image-to-image"
_KIE_UPLOAD_PATH = "logo-play/references"
_KIE_POLL_ATTEMPTS = 60
_KIE_POLL_INTERVAL_SECONDS = 2.0
PROMPT_OPTIMIZATION_STATUS = "upstream_not_configurable"
KIE_GPT_IMAGE_MODEL_ID = "gpt-image-2"
KIE_GPT_IMAGE_MODEL_ALIASES = {
    KIE_GPT_IMAGE_MODEL_ID,
    _KIE_TEXT_TO_IMAGE_MODEL,
    _KIE_IMAGE_TO_IMAGE_MODEL,
}
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


@dataclass(frozen=True, slots=True)
class SeedreamRequestProfile:
    """Provider request fields and native output contract for one model family."""

    family: str
    max_input_images: int
    size: str
    output_width: int
    output_height: int
    sequential_image_generation: Literal["disabled"] | None


_SEEDREAM_40_PROFILE = SeedreamRequestProfile("seedream_4_0", 9, "1300x1300", 1300, 1300, "disabled")
_SEEDREAM_45_PROFILE = SeedreamRequestProfile("seedream_4_5", 9, "2048x2048", 2048, 2048, "disabled")
_SEEDREAM_50_PRO_PROFILE = SeedreamRequestProfile("seedream_5_0_pro", 9, "2048x2048", 2048, 2048, None)
_SEEDREAM_50_LITE_PROFILE = SeedreamRequestProfile(
    "seedream_5_0_lite", 9, "2048x2048", 2048, 2048, "disabled"
)


class ProviderError(RuntimeError):
    """Normalized supplier failure without raw body, URL, or authorization details."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status_family: ProviderStatusFamily | None = None,
        provider_http_status: int | None = None,
        response_image_count: int | None = None,
        provider_request_id_hash: str | None = None,
        provider_operation: ProviderOperation | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status_family = http_status_family
        self.provider_http_status = provider_http_status
        self.response_image_count = response_image_count
        self.provider_request_id_hash = provider_request_id_hash
        self.provider_operation = provider_operation


@dataclass(frozen=True, slots=True)
class ImageToImageRequest:
    """Supplier-neutral, exactly-one-reference-image generation request."""

    model_id: str
    api_key: str
    reference_image: bytes
    reference_media_type: str
    prompt: str
    max_input_images: int | None = 9
    output_count: int = 1


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    """Supplier-neutral generation request with an optional ordered image set."""

    model_id: str
    api_key: str
    prompt: str
    reference_image: bytes | None = None
    reference_media_type: str | None = None
    reference_images: tuple[tuple[bytes, str], ...] = ()
    max_input_images: int | None = 9
    output_count: int = 1


@dataclass(frozen=True, slots=True)
class ImageToImageResult:
    """Safe provider metadata plus an in-memory, already-validated diagnostic image."""

    provider_request_id_hash: str | None = None
    provider_http_status: int | None = None
    response_image_count: int | None = None
    diagnostic_capture_status: DiagnosticCaptureStatus = "not_attempted"
    diagnostic_image: bytes | None = None
    diagnostic_media_type: DiagnosticImageMediaType | None = None
    provider_task_id: str | None = None
    credits_consumed: int | float | None = None


@dataclass(frozen=True, slots=True)
class KieTaskSubmission:
    """The only Kie creation response field needed for durable recovery."""

    task_id: str
    provider_http_status: int


class ImageGenerationProvider(Protocol):
    """Common surface implemented by synchronous and asynchronous adapters."""

    async def image_to_image(
        self, api_url: str, request: ImageToImageRequest
    ) -> ImageToImageResult: ...

    async def generate(
        self, api_url: str, request: ImageGenerationRequest
    ) -> ImageToImageResult: ...


class DoubaoSeedreamProvider:
    """Translate the unified request to the Seedream image generation protocol."""

    async def image_to_image(
        self, api_url: str, request: ImageToImageRequest
    ) -> ImageToImageResult:
        """Keep the required-reference wrapper used by smoke tests and single-image editing."""

        return await self.generate(
            api_url,
            ImageGenerationRequest(
                model_id=request.model_id,
                api_key=request.api_key,
                prompt=request.prompt,
                reference_image=request.reference_image,
                reference_media_type=request.reference_media_type,
                max_input_images=request.max_input_images,
                output_count=request.output_count,
            ),
        )

    async def generate(self, api_url: str, request: ImageGenerationRequest) -> ImageToImageResult:
        """Send text-to-image or image-to-image based on the optional reference pair."""

        if request.output_count != 1:
            raise ProviderError(
                "invalid_output_count", "Image generation requires exactly one output"
            )
        has_reference_bytes = request.reference_image is not None
        has_reference_media_type = request.reference_media_type is not None
        if request.reference_images and (
            request.reference_image is not None or request.reference_media_type is not None
        ):
            raise ProviderError(
                "invalid_reference_input", "Use either reference_image or reference_images"
            )
        if has_reference_bytes != has_reference_media_type:
            raise ProviderError(
                "invalid_reference_input",
                "Reference image bytes and media type must be supplied together",
            )
        if request.reference_image is not None and len(request.reference_image) == 0:
            raise ProviderError("missing_reference_image", "The reference image is unavailable")
        if any(not content or not media_type for content, media_type in request.reference_images):
            raise ProviderError(
                "invalid_reference_input", "Reference image bytes and media type are required"
            )
        if len(request.reference_images) > 9:
            raise ProviderError(
                "invalid_reference_input", "At most nine ordered input images are supported"
            )
        profile = seedream_request_profile(request.model_id)
        payload: dict[str, Any] = {
            "model": request.model_id,
            "prompt": request.prompt,
            "response_format": "url",
            "size": profile.size,
            "watermark": False,
        }
        reference_pairs = request.reference_images
        if request.reference_image is not None and request.reference_media_type is not None:
            reference_pairs = ((request.reference_image, request.reference_media_type),)
        if len(reference_pairs) > 9:
            raise ProviderError(
                "invalid_reference_input", "At most nine ordered input images are supported"
            )
        if reference_pairs and request.max_input_images is None:
            raise ProviderError(
                "reference_input_limit_exceeded",
                "Provider request must declare its maximum input image count",
            )
        if request.max_input_images is not None and len(reference_pairs) > request.max_input_images:
            raise ProviderError(
                "reference_input_limit_exceeded",
                "Provider request exceeds its declared maximum input image count",
            )
        if reference_pairs:
            image_data_url = (
                f"data:{reference_pairs[0][1]};base64,"
                f"{base64.b64encode(reference_pairs[0][0]).decode('ascii')}"
            )
            if len(reference_pairs) == 1:
                payload["image"] = image_data_url
            else:
                payload["image"] = [
                    f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
                    for content, media_type in reference_pairs
                ]
        if profile.sequential_image_generation is not None:
            payload["sequential_image_generation"] = profile.sequential_image_generation
        timeout = httpx.Timeout(
            connect=_PROVIDER_CONNECT_TIMEOUT_SECONDS,
            write=_PROVIDER_WRITE_TIMEOUT_SECONDS,
            read=_PROVIDER_READ_TIMEOUT_SECONDS,
            pool=_PROVIDER_POOL_TIMEOUT_SECONDS,
        )
        try:
            async with httpx.AsyncClient(
                timeout=timeout, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.post(
                    api_url,
                    headers={"Authorization": f"Bearer {request.api_key}"},
                    json=payload,
                )
                return await self._result_from_response(response, client, profile)
        except httpx.TimeoutException as error:
            raise ProviderError("timeout", "Model service timed out") from error
        except httpx.HTTPError as error:
            raise ProviderError("network_error", "Model service is unavailable") from error

    async def _result_from_response(
        self,
        response: httpx.Response,
        client: httpx.AsyncClient,
        profile: SeedreamRequestProfile,
    ) -> ImageToImageResult:
        """Normalize a generation response and capture its first image in memory only."""

        request_id_hash = _request_id_hash(response.headers.get("x-request-id"))
        if response.status_code in {401, 403}:
            raise ProviderError(
                "provider_auth_failed",
                "Model service rejected the connection credential",
                "http_4xx",
                response.status_code,
                provider_request_id_hash=request_id_hash,
            )
        if response.status_code == 429:
            raise ProviderError(
                "provider_rate_limited",
                "Model service rate limit reached",
                "http_4xx",
                response.status_code,
                provider_request_id_hash=request_id_hash,
            )
        if response.status_code >= 500:
            raise ProviderError(
                "provider_unavailable",
                "Model service is temporarily unavailable",
                "http_5xx",
                response.status_code,
                provider_request_id_hash=request_id_hash,
            )
        if response.status_code >= 400:
            raise ProviderError(
                "provider_validation_failed",
                "Model service rejected the controlled test input",
                "http_4xx",
                response.status_code,
                provider_request_id_hash=request_id_hash,
            )
        try:
            body = response.json()
            images = body.get("data") if isinstance(body, dict) else None
            if not isinstance(images, list) or not images:
                raise ValueError("missing generated image")
            body_request_id = body.get("request_id")
            if request_id_hash is None and isinstance(body_request_id, str):
                request_id_hash = _request_id_hash(body_request_id)
        except (ValueError, TypeError):
            raise ProviderError(
                "invalid_provider_response",
                "Model service returned no generated image",
                provider_http_status=response.status_code,
                response_image_count=0,
                provider_request_id_hash=request_id_hash,
            ) from None

        image_url = _first_https_image_url(images)
        captured = (
            await self._download_diagnostic_image(client, image_url, profile)
            if image_url is not None
            else None
        )
        if captured is None:
            return ImageToImageResult(
                provider_request_id_hash=request_id_hash,
                provider_http_status=response.status_code,
                response_image_count=len(images),
                diagnostic_capture_status="failed",
            )
        image, media_type = captured
        return ImageToImageResult(
            provider_request_id_hash=request_id_hash,
            provider_http_status=response.status_code,
            response_image_count=len(images),
            diagnostic_capture_status="captured",
            diagnostic_image=image,
            diagnostic_media_type=media_type,
        )

    async def _download_diagnostic_image(
        self,
        client: httpx.AsyncClient,
        image_url: str,
        profile: SeedreamRequestProfile,
    ) -> tuple[bytes, DiagnosticImageMediaType] | None:
        """Download only a validated supplier result without retaining its temporary URL."""

        try:
            async with client.stream("GET", image_url, headers={"Accept": "image/*"}) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    return None
                media_type = _response_media_type(response.headers.get("content-type"))
                if media_type is None or _exceeds_download_limit(
                    response.headers.get("content-length")
                ):
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_DIAGNOSTIC_IMAGE_BYTES:
                        return None
        except httpx.HTTPError:
            return None

        image = bytes(content)
        return (
            (image, media_type)
            if _signature_matches_media_type(image, media_type, profile)
            else None
        )


class KieGptImageProvider:
    """Translate the logical GPT Image 2 model to Kie's asynchronous job API."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_attempts: int = _KIE_POLL_ATTEMPTS,
        poll_interval_seconds: float = _KIE_POLL_INTERVAL_SECONDS,
    ) -> None:
        if poll_attempts < 1 or poll_interval_seconds < 0:
            raise ValueError("Invalid Kie polling configuration")
        self._transport = transport
        self._poll_attempts = poll_attempts
        self._poll_interval_seconds = poll_interval_seconds

    async def image_to_image(
        self, api_url: str, request: ImageToImageRequest
    ) -> ImageToImageResult:
        """Run a complete task for the connection smoke-test path."""

        return await self.generate(
            api_url,
            ImageGenerationRequest(
                model_id=request.model_id,
                api_key=request.api_key,
                prompt=request.prompt,
                reference_image=request.reference_image,
                reference_media_type=request.reference_media_type,
                max_input_images=request.max_input_images,
                output_count=request.output_count,
            ),
        )

    async def generate(self, api_url: str, request: ImageGenerationRequest) -> ImageToImageResult:
        """Submit then poll a task when no durable business record is involved."""

        submission = await self.submit(api_url, request)
        return await self.wait_for_result(request.api_key, submission.task_id)

    async def submit(self, api_url: str, request: ImageGenerationRequest) -> KieTaskSubmission:
        """Upload ordered references and create exactly one Kie task."""

        reference_pairs = _validated_reference_pairs(request)
        _validate_kie_configuration(api_url, request.model_id)
        timeout = _provider_timeout()
        headers = {"Authorization": f"Bearer {request.api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                input_urls = [
                    await self._upload_reference(client, headers, content, media_type)
                    for content, media_type in reference_pairs
                ]
                task_input: dict[str, Any] = {
                    "prompt": request.prompt,
                    "aspect_ratio": "1:1",
                    "resolution": "1K",
                }
                provider_model = _KIE_TEXT_TO_IMAGE_MODEL
                if input_urls:
                    provider_model = _KIE_IMAGE_TO_IMAGE_MODEL
                    task_input["input_urls"] = input_urls
                try:
                    response = await client.post(
                        _KIE_CREATE_TASK_URL,
                        headers=headers,
                        json={"model": provider_model, "input": task_input},
                    )
                except (httpx.TimeoutException, httpx.HTTPError) as error:
                    raise ProviderError(
                        "provider_submission_uncertain",
                        "Model task submission outcome is unknown",
                        provider_operation="task_create",
                    ) from error
        except ProviderError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderError("timeout", "Model service timed out") from error
        except httpx.HTTPError as error:
            raise ProviderError("network_error", "Model service is unavailable") from error

        body = _kie_response_body(response, "task_create")
        data = body.get("data")
        task_id = data.get("taskId") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id.strip()) > 255:
            raise ProviderError(
                "provider_submission_uncertain",
                "Model service returned no recoverable task identifier",
                provider_http_status=response.status_code,
                provider_operation="task_create",
            )
        return KieTaskSubmission(task_id=task_id.strip(), provider_http_status=response.status_code)

    async def wait_for_result(self, api_key: str, task_id: str) -> ImageToImageResult:
        """Poll one already-created task and download its first native image."""

        if not api_key.strip() or not task_id.strip():
            raise ProviderError("invalid_provider_task", "Model task is unavailable")
        timeout = _provider_timeout()
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                for attempt in range(self._poll_attempts):
                    response = await client.get(
                        _KIE_TASK_INFO_URL,
                        headers=headers,
                        params={"taskId": task_id},
                    )
                    body = _kie_response_body(response, "task_poll")
                    data = body.get("data")
                    if not isinstance(data, dict):
                        raise ProviderError(
                            "invalid_provider_response",
                            "Model service returned an invalid task record",
                            provider_http_status=response.status_code,
                            provider_operation="task_poll",
                        )
                    state = data.get("state")
                    if state in {"waiting", "queuing", "generating"}:
                        if attempt + 1 < self._poll_attempts:
                            await asyncio.sleep(self._poll_interval_seconds)
                        continue
                    if state == "fail":
                        raise ProviderError(
                            "provider_task_failed",
                            "Model task failed",
                            provider_http_status=response.status_code,
                            provider_request_id_hash=_request_id_hash(task_id),
                            provider_operation="task_poll",
                        )
                    if state != "success":
                        raise ProviderError(
                            "invalid_provider_response",
                            "Model service returned an unsupported task state",
                            provider_http_status=response.status_code,
                            provider_request_id_hash=_request_id_hash(task_id),
                            provider_operation="task_poll",
                        )
                    image_urls = _kie_result_urls(data.get("resultJson"))
                    if len(image_urls) != 1:
                        raise ProviderError(
                            "invalid_provider_response",
                            "Model task returned an unexpected image count",
                            provider_http_status=response.status_code,
                            response_image_count=len(image_urls),
                            provider_request_id_hash=_request_id_hash(task_id),
                            provider_operation="task_poll",
                        )
                    image_url = _first_https_url(image_urls)
                    captured = (
                        await self._download_result_image(client, image_url)
                        if image_url is not None
                        else None
                    )
                    if captured is None:
                        raise ProviderError(
                            "invalid_generated_image",
                            "Model task returned no valid generated image",
                            provider_http_status=response.status_code,
                            response_image_count=len(image_urls),
                            provider_request_id_hash=_request_id_hash(task_id),
                            provider_operation="result_download",
                        )
                    image, media_type = captured
                    return ImageToImageResult(
                        provider_request_id_hash=_request_id_hash(task_id),
                        provider_http_status=response.status_code,
                        response_image_count=len(image_urls),
                        diagnostic_capture_status="captured",
                        diagnostic_image=image,
                        diagnostic_media_type=media_type,
                        provider_task_id=task_id,
                        credits_consumed=_safe_number(data.get("creditsConsumed")),
                    )
        except ProviderError:
            raise
        except httpx.TimeoutException as error:
            raise ProviderError(
                "timeout", "Model service timed out", provider_operation="task_poll"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(
                "network_error",
                "Model service is unavailable",
                provider_operation="task_poll",
            ) from error
        raise ProviderError(
            "provider_poll_timeout",
            "Model task did not finish within the polling window",
            provider_request_id_hash=_request_id_hash(task_id),
            provider_operation="task_poll",
        )

    async def _upload_reference(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        content: bytes,
        media_type: str,
    ) -> str:
        suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
        suffix = suffixes[media_type]
        try:
            response = await client.post(
                _KIE_UPLOAD_URL,
                headers=headers,
                data={"uploadPath": _KIE_UPLOAD_PATH, "fileName": f"reference{suffix}"},
                files={"file": (f"reference{suffix}", content, media_type)},
            )
        except httpx.TimeoutException as error:
            raise ProviderError(
                "timeout", "Model service timed out", provider_operation="reference_upload"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError(
                "network_error",
                "Model service is unavailable",
                provider_operation="reference_upload",
            ) from error
        body = _kie_response_body(response, "reference_upload")
        data = body.get("data")
        download_url = data.get("downloadUrl") if isinstance(data, dict) else None
        if not isinstance(download_url, str) or not _is_safe_https_url(download_url):
            raise ProviderError(
                "reference_upload_failed",
                "Reference image upload returned no safe URL",
                provider_http_status=response.status_code,
                provider_operation="reference_upload",
            )
        return download_url

    async def _download_result_image(
        self, client: httpx.AsyncClient, image_url: str
    ) -> tuple[bytes, DiagnosticImageMediaType] | None:
        try:
            async with client.stream(
                "GET", image_url, headers={"Accept": "image/png,image/jpeg"}
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    return None
                media_type = _response_media_type(response.headers.get("content-type"))
                if media_type is None or _exceeds_download_limit(
                    response.headers.get("content-length")
                ):
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_DIAGNOSTIC_IMAGE_BYTES:
                        return None
        except httpx.HTTPError:
            return None
        image = bytes(content)
        return (image, media_type) if _is_square_native_image(image, media_type) else None


def seedream_request_profile(model_id: str) -> SeedreamRequestProfile:
    """Select provider parameters from a recognizable Seedream model version."""

    normalized = model_id.strip().lower().replace(".", "-").replace("_", "-")
    if "seedream-4-5" in normalized:
        return _SEEDREAM_45_PROFILE
    if "seedream-5-0" in normalized:
        return _SEEDREAM_50_LITE_PROFILE if "lite" in normalized else _SEEDREAM_50_PRO_PROFILE
    return _SEEDREAM_40_PROFILE


def image_provider_for_connection(
    provider: str,
    model_id: str,
    override: ImageGenerationProvider | None = None,
) -> ImageGenerationProvider:
    """Resolve a configured connection before any supplier request is sent."""

    if override is not None:
        return override
    normalized_provider = provider.strip().casefold()
    normalized_model = model_id.strip().casefold()
    if normalized_provider == "kie":
        if normalized_model not in KIE_GPT_IMAGE_MODEL_ALIASES:
            raise ProviderError("unsupported_model", "Unsupported Kie image model")
        return KieGptImageProvider()
    if normalized_provider in {"火山方舟", "volcengine", "doubao", "volcano engine"}:
        if "seedream" not in normalized_model:
            raise ProviderError("unsupported_model", "Unsupported Seedream image model")
        return DoubaoSeedreamProvider()
    raise ProviderError("unsupported_provider", "Unsupported image model provider")


def provider_adapter_name(provider: str, model_id: str) -> str:
    """Return a safe audit label without exposing supplier request content."""

    if (
        provider.strip().casefold() == "kie"
        and model_id.strip().casefold() in KIE_GPT_IMAGE_MODEL_ALIASES
    ):
        return "kie_gpt_image_2"
    return "doubao_seedream"


def fixed_rendering_metadata(model_id: str = "") -> dict[str, str | int | bool]:
    """Return the safe, non-overridable rendering contract for audit summaries."""

    if model_id.strip().casefold() in KIE_GPT_IMAGE_MODEL_ALIASES:
        return {
            "adapter_profile": "kie_gpt_image_2",
            "max_input_images": 9,
            "aspect_ratio": "1:1",
            "resolution": "1K",
            "output_count": 1,
            "output_mime_type": "image/png_or_jpeg",
        }
    profile = seedream_request_profile(model_id)
    return {
        "adapter_profile": profile.family,
        "max_input_images": profile.max_input_images,
        "request_size": profile.size,
        "output_mime_type": "image/jpeg",
        "output_width": profile.output_width,
        "output_height": profile.output_height,
        "watermark_requested": False,
    }


def is_valid_native_output(image: bytes, media_type: str | None, model_id: str = "") -> bool:
    """Validate the fixed business output contract before it is persisted."""

    if model_id.strip().casefold() in KIE_GPT_IMAGE_MODEL_ALIASES:
        return media_type in {"image/png", "image/jpeg"} and _is_square_native_image(
            image, media_type
        )
    return media_type == "image/jpeg" and _signature_matches_media_type(
        image, "image/jpeg", seedream_request_profile(model_id)
    )


def _provider_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=_PROVIDER_CONNECT_TIMEOUT_SECONDS,
        write=_PROVIDER_WRITE_TIMEOUT_SECONDS,
        read=_PROVIDER_READ_TIMEOUT_SECONDS,
        pool=_PROVIDER_POOL_TIMEOUT_SECONDS,
    )


def _validated_reference_pairs(
    request: ImageGenerationRequest,
) -> tuple[tuple[bytes, str], ...]:
    if request.output_count != 1:
        raise ProviderError("invalid_output_count", "Image generation requires exactly one output")
    if not request.api_key.strip() or not request.prompt.strip():
        raise ProviderError("invalid_provider_request", "Image generation input is unavailable")
    if request.reference_images and (
        request.reference_image is not None or request.reference_media_type is not None
    ):
        raise ProviderError(
            "invalid_reference_input", "Use either reference_image or reference_images"
        )
    if (request.reference_image is None) != (request.reference_media_type is None):
        raise ProviderError(
            "invalid_reference_input",
            "Reference image bytes and media type must be supplied together",
        )
    pairs = request.reference_images
    if request.reference_image is not None and request.reference_media_type is not None:
        pairs = ((request.reference_image, request.reference_media_type),)
    if len(pairs) > 9:
        raise ProviderError(
            "invalid_reference_input", "At most nine ordered input images are supported"
        )
    if pairs and request.max_input_images is None:
        raise ProviderError(
            "reference_input_limit_exceeded",
            "Provider request must declare its maximum input image count",
        )
    if request.max_input_images is not None and len(pairs) > request.max_input_images:
        raise ProviderError(
            "reference_input_limit_exceeded",
            "Provider request exceeds its declared maximum input image count",
        )
    if any(
        not content or media_type not in {"image/png", "image/jpeg", "image/webp"}
        for content, media_type in pairs
    ):
        raise ProviderError(
            "invalid_reference_input", "Reference images must be PNG, JPEG, or WebP"
        )
    return pairs


def _validate_kie_configuration(api_url: str, model_id: str) -> None:
    if model_id.strip().casefold() not in KIE_GPT_IMAGE_MODEL_ALIASES:
        raise ProviderError("unsupported_model", "Unsupported Kie image model")
    if api_url.rstrip("/") != _KIE_CREATE_TASK_URL:
        raise ProviderError("invalid_provider_url", "Kie task creation URL is invalid")


def _kie_response_body(
    response: httpx.Response, operation: ProviderOperation | None = None
) -> dict[str, Any]:
    _raise_for_provider_status(response.status_code, operation)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ProviderError(
            "invalid_provider_response",
            "Model service returned an invalid response",
            provider_http_status=response.status_code,
            provider_operation=operation,
        )
    code = body.get("code")
    if isinstance(code, int) and code != 200:
        _raise_for_provider_status(code, operation)
        raise ProviderError(
            "provider_validation_failed",
            "Model service rejected the request",
            "http_4xx" if 400 <= code < 500 else None,
            response.status_code,
            provider_operation=operation,
        )
    return body


def _raise_for_provider_status(
    status_code: int, operation: ProviderOperation | None = None
) -> None:
    status_family: ProviderStatusFamily | None = None
    if 400 <= status_code < 500:
        status_family = "http_4xx"
    elif status_code >= 500:
        status_family = "http_5xx"
    if status_code in {401, 403}:
        raise ProviderError(
            "provider_auth_failed",
            "Model service rejected the connection credential",
            "http_4xx",
            status_code,
            provider_operation=operation,
        )
    if status_code == 402:
        raise ProviderError(
            "provider_quota_exhausted",
            "Model service account has insufficient credits",
            "http_4xx",
            status_code,
            provider_operation=operation,
        )
    if status_code == 429:
        raise ProviderError(
            "provider_rate_limited",
            "Model service rate limit reached",
            "http_4xx",
            status_code,
            provider_operation=operation,
        )
    if status_code >= 500:
        raise ProviderError(
            "provider_unavailable",
            "Model service is temporarily unavailable",
            "http_5xx",
            status_code,
            provider_operation=operation,
        )
    if status_code >= 400:
        raise ProviderError(
            "provider_validation_failed",
            "Model service rejected the request",
            status_family,
            status_code,
            provider_operation=operation,
        )


def _kie_result_urls(result_json: object) -> list[str]:
    if not isinstance(result_json, str):
        return []
    try:
        result = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return []
    urls = result.get("resultUrls") if isinstance(result, dict) else None
    return [value for value in urls if isinstance(value, str)] if isinstance(urls, list) else []


def _safe_number(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _request_id_hash(request_id: str | None) -> str | None:
    """Return the one-way traceable form of a supplier request identifier."""

    return sha256(request_id.encode("utf-8")).hexdigest() if request_id else None


def _first_https_image_url(images: list[Any]) -> str | None:
    """Accept the first response URL only when it is a direct HTTPS address."""

    first = images[0]
    value = first.get("url") if isinstance(first, dict) else None
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def _first_https_url(urls: list[str]) -> str | None:
    return urls[0] if urls and _is_safe_https_url(urls[0]) else None


def _is_safe_https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _response_media_type(value: str | None) -> DiagnosticImageMediaType | None:
    """Accept only generated image formats supported by business storage."""

    if value is None:
        return None
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type == "image/jpeg":
        return "image/jpeg"
    return "image/png" if media_type == "image/png" else None


def _exceeds_download_limit(content_length: str | None) -> bool:
    """Reject malformed or oversized declared response bodies before reading them."""

    if content_length is None:
        return False
    try:
        return int(content_length) > _MAX_DIAGNOSTIC_IMAGE_BYTES
    except ValueError:
        return True


def _signature_matches_media_type(
    image: bytes,
    media_type: DiagnosticImageMediaType,
    profile: SeedreamRequestProfile,
) -> bool:
    """Require native JPEG magic, footer, and exact output dimensions before persistence."""

    return (
        media_type == "image/jpeg"
        and len(image) >= 4
        and image.startswith(b"\xff\xd8\xff")
        and image.endswith(b"\xff\xd9")
        and _jpeg_dimensions(image) == (profile.output_width, profile.output_height)
    )


def _is_square_native_image(image: bytes, media_type: str) -> bool:
    dimensions: tuple[int, int] | None = None
    if media_type == "image/png":
        dimensions = _png_dimensions(image)
    elif media_type == "image/jpeg":
        dimensions = _jpeg_dimensions(image)
    return dimensions is not None and dimensions[0] == dimensions[1]


def _png_dimensions(image: bytes) -> tuple[int, int] | None:
    """Read PNG dimensions from the required leading IHDR chunk."""

    if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if struct.unpack(">I", image[8:12])[0] != 13 or image[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", image[16:24])
    return (width, height) if width > 0 and height > 0 else None


def _jpeg_dimensions(image: bytes) -> tuple[int, int] | None:
    """Read dimensions from a validated JPEG start-of-frame segment without decoding pixels."""

    if len(image) < 10 or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
        return None
    offset = 2
    while offset + 1 < len(image):
        if image[offset] != 0xFF:
            return None
        while offset < len(image) and image[offset] == 0xFF:
            offset += 1
        if offset >= len(image):
            return None
        marker = image[offset]
        offset += 1
        if marker == 0xD9:
            return None
        if marker in {0x01, *range(0xD0, 0xD8)}:
            continue
        if offset + 2 > len(image):
            return None
        segment_length = int.from_bytes(image[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(image):
            return None
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 8:
                return None
            height = int.from_bytes(image[offset + 3 : offset + 5], "big")
            width = int.from_bytes(image[offset + 5 : offset + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        if marker == 0xDA:
            return None
        offset += segment_length
    return None
