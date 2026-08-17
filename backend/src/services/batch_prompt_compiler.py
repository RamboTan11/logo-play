"""Pure deterministic compiler and validation helpers for batch image strategies."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from src.db.models import AssetRecord
from src.models.batch_generation_policy import (
    BatchPolicyPayload,
    BatchPromptTemplateDto,
    BatchStyleDto,
    StrategyValidationErrorDto,
)

PROMPT_COMPILER_VERSION = "logo-prompt-compiler-v4"
BATCH_RULE_SET_VERSION = "batch-flat-draft-v1"
BATCH_OUTPUT_CONSTRAINT = (
    "输出平面创意初稿；默认禁止 3D 样机、实景招牌、包装 mockup 和环境光影展示；"
    "输出 1 张完整、清晰、适合品牌继续优化的 Logo 图片，不输出多图拼版、解释文字或供应商参数。"
)
CUSTOMER_SOURCE_RULES = (
    "客户源图只作为品牌识别、内容结构和用户点名部分的锚点；模板参考图只作为风格参考；"
    "现有模板决定整体风格、规范、构图和配色；用户明确点名部分可以覆盖对应要求，"
    "未点名的核心识别元素保留；禁止照搬客户图的材质、光影、背景、样机呈现或低质细节。"
)
DEFAULT_REFERENCE_REQUIREMENT = "无额外参考要求"
REPLENISHMENT_BUDGET = 2

_TEMPLATE_VARIABLE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


@dataclass(frozen=True, slots=True)
class BatchCompileContext:
    """Database facts needed by the pure compiler without any secret or provider data."""

    model_connection_id: str | None
    model_connection_version: int | None
    image_to_image_verified: bool
    assets: Mapping[str, AssetRecord]
    max_input_images: int | None = None


@dataclass(frozen=True, slots=True)
class BatchTemplateCombination:
    """One complete template with its optional reference allocated for generation."""

    style_id: str
    template_id: str
    reference_image_asset_ids: tuple[str, ...]

    @property
    def reference_image_asset_id(self) -> str | None:
        return self.reference_image_asset_ids[0] if self.reference_image_asset_ids else None


@dataclass(frozen=True, slots=True)
class BatchPromptCompilation:
    """Internal batch-runtime input derived from one immutable template combination."""

    compiled_prompt: str
    normalized_domain: str
    generation_mode: Literal["text_to_image", "image_to_image"]
    reference_image_asset_ids: tuple[str, ...]
    reference_image_content_hashes: tuple[str, ...]
    compiler_version: str
    output_constraint: str
    requirement_binding: Literal["template_variable", "compatibility_block"]
    rule_set_version: str

    @property
    def reference_image_asset_id(self) -> str | None:
        return self.reference_image_asset_ids[0] if self.reference_image_asset_ids else None

    @property
    def reference_image_content_hash(self) -> str | None:
        return self.reference_image_content_hashes[0] if self.reference_image_content_hashes else None


class BatchPromptCompilationError(ValueError):
    """Keep runtime compilation failures structured without exposing a public compiler API."""

    def __init__(self, validation_errors: list[StrategyValidationErrorDto]) -> None:
        super().__init__("batch_prompt_compilation_failed")
        self.validation_errors = validation_errors


class ReferenceInputQuotaError(ValueError):
    """Raised before any provider upload when the complete ordered input is unsafe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_reference_input_quota(
    *, customer_source_count: int, template_reference_count: int, max_input_images: int | None
) -> None:
    """Validate role quotas and provider capacity without modifying or truncating input."""

    if customer_source_count < 0 or customer_source_count > 1:
        raise ReferenceInputQuotaError("reference_image_limit_exceeded", "客户视觉源图最多 1 张")
    if template_reference_count < 0 or template_reference_count > 8:
        raise ReferenceInputQuotaError("reference_image_limit_exceeded", "模板参考图最多 8 张")
    total = customer_source_count + template_reference_count
    if total > 9:
        raise ReferenceInputQuotaError("reference_image_limit_exceeded", "单候选最终输入最多 9 张")
    if total and (max_input_images is None or max_input_images < total):
        raise ReferenceInputQuotaError(
            "reference_guided_runtime_unavailable",
            "当前模型未显式声明足够的参考图输入上限",
        )


def compile_batch_prompt(
    *,
    policy: BatchPolicyPayload,
    domain: str,
    style_id: str,
    template_id: str,
    context: BatchCompileContext,
    user_reference_requirement: str | None = None,
    customer_source_present: bool = False,
) -> BatchPromptCompilation:
    """Compile one runtime template/reference pair with the canonical fixed block order."""

    errors = validate_batch_policy(policy, context)
    style = next((item for item in policy.styles if item.id == style_id), None)
    template = next((item for item in style.templates if item.id == template_id), None) if style else None
    if style is None:
        errors.append(_error("style_id", "required", "未找到运行时风格"))
    if template is None:
        errors.append(_error("template_id", "required", "未找到运行时模板"))

    reference_ids = tuple(template.reference_images) if template else ()
    reference_assets = tuple(context.assets[asset_id] for asset_id in reference_ids if asset_id in context.assets)
    normalized_domain = normalize_domain(domain)
    if normalized_domain is None:
        errors.append(_error("domain", "required", "请输入品牌信息"))
    if errors or style is None or template is None or normalized_domain is None:
        raise BatchPromptCompilationError(errors)

    normalized_requirement = normalize_reference_requirement(user_reference_requirement)
    variables = _variable_names(template.positive_prompt)
    requirement_binding: Literal["template_variable", "compatibility_block"] = (
        "template_variable" if "用户参考要求" in variables else "compatibility_block"
    )
    positive = _replace_variable(template.positive_prompt, "域名", normalized_domain)
    positive = _replace_variable(positive, "用户参考要求", normalized_requirement)
    negative = _replace_variable(template.negative_prompt or "", "域名", normalized_domain)
    sections = [
        ("正向内容", positive),
    ]
    if requirement_binding == "compatibility_block":
        sections.append(("用户参考要求", f"用户参考要求：{normalized_requirement}"))
    if customer_source_present:
        sections.append(("客户源图规则", CUSTOMER_SOURCE_RULES))
    if negative.strip():
        sections.append(("负向避免项", negative))
    sections.append(
        ("输出约束", BATCH_OUTPUT_CONSTRAINT),
    )
    sections = [section for section in sections if section[1].strip()]
    compiled_prompt = _compose_prompt(sections)
    return BatchPromptCompilation(
        compiled_prompt=compiled_prompt,
        normalized_domain=normalized_domain,
        generation_mode="image_to_image" if reference_assets else "text_to_image",
        reference_image_asset_ids=tuple(asset.asset_id for asset in reference_assets),
        reference_image_content_hashes=tuple(asset.content_hash for asset in reference_assets),
        compiler_version=PROMPT_COMPILER_VERSION,
        output_constraint=BATCH_OUTPUT_CONSTRAINT,
        requirement_binding=requirement_binding,
        rule_set_version=BATCH_RULE_SET_VERSION,
    )


def validate_batch_policy(
    policy: BatchPolicyPayload, context: BatchCompileContext
) -> list[StrategyValidationErrorDto]:
    """Return all field errors without mutating the browser's unpublished draft."""

    errors: list[StrategyValidationErrorDto] = []
    if (
        not policy.model_connection_id
        or policy.model_connection_id != context.model_connection_id
        or not context.image_to_image_verified
    ):
        errors.append(
            _error("model_connection_id", "unverified_model_connection", "请选择已通过图生图能力测试的模型连接")
        )
    if not policy.styles:
        errors.append(_error("styles", "required", "请至少新增一个风格类型"))

    for style_index, style in enumerate(policy.styles):
        style_prefix = f"styles[{style_index}]"
        if not style.name.strip():
            errors.append(_error(f"{style_prefix}.name", "required", "请填写风格名称"))
        complete_template_count = 0
        for template_index, template in enumerate(style.templates):
            template_errors = _validate_template(
                template,
                f"{style_prefix}.templates[{template_index}]",
                context.assets,
            )
            if not template_errors:
                complete_template_count += 1
            errors.extend(template_errors)
        if style.generation_count > 0 and complete_template_count == 0:
            errors.append(
                _error(f"{style_prefix}.generation_count", "required", "创建完整模板后才可设置生成数")
            )
    total_generation_count = sum(style.generation_count for style in policy.styles)
    if total_generation_count > 9:
        errors.append(
            _error(
                "styles",
                "invalid_generation_count",
                f"所有风格本轮合计最多生成 9 张图片，当前为 {total_generation_count} 张",
            )
        )
    return errors


def normalize_domain(value: str) -> str | None:
    """Trim the customer brand input without enforcing a domain format."""

    candidate = value.strip()
    return candidate or None


def normalize_reference_requirement(value: str | None) -> str:
    """Normalize optional customer guidance to one deterministic compiler value."""

    normalized = (value or "").strip()
    return normalized or DEFAULT_REFERENCE_REQUIREMENT


def rotate_complete_template_combinations(
    styles: list[BatchStyleDto], cursors: Mapping[str, int]
) -> tuple[list[BatchTemplateCombination], dict[str, int]]:
    """Allocate complete template/reference pairs per style without splitting the pair."""

    combinations: list[BatchTemplateCombination] = []
    next_cursors: dict[str, int] = {}
    for style in styles:
        complete_templates = [
            template
            for template in style.templates
            if _is_structurally_complete_template(template)
        ]
        if style.generation_count == 0 or not complete_templates:
            continue
        start = cursors.get(style.id, 0) % len(complete_templates)
        for offset in range(style.generation_count):
            template = complete_templates[(start + offset) % len(complete_templates)]
            combinations.append(
                BatchTemplateCombination(
                    style_id=style.id,
                    template_id=template.id,
                    reference_image_asset_ids=tuple(template.reference_images),
                )
            )
        next_cursors[style.id] = (start + style.generation_count) % len(complete_templates)
    return combinations, next_cursors


def _validate_template(
    template: BatchPromptTemplateDto,
    field_prefix: str,
    assets: Mapping[str, AssetRecord],
) -> list[StrategyValidationErrorDto]:
    errors: list[StrategyValidationErrorDto] = []
    if not template.name.strip():
        errors.append(_error(f"{field_prefix}.name", "required", "请填写模板名称"))
    if len(template.reference_images) > 8:
        errors.append(_error(f"{field_prefix}.reference_images", "invalid_reference_image", "参考图最多支持 8 张"))
    if len(set(template.reference_images)) != len(template.reference_images):
        errors.append(_error(f"{field_prefix}.reference_images", "invalid_reference_image", "参考图不能重复"))
    for index, asset_id in enumerate(template.reference_images):
        if asset_id not in assets:
            errors.append(_error(f"{field_prefix}.reference_images[{index}]", "invalid_reference_image", "参考图资产无效，请重新上传"))
    if not template.positive_prompt.strip():
        errors.append(_error(f"{field_prefix}.positive_prompt", "required", "请填写正提示词"))
    elif "域名" not in _variable_names(template.positive_prompt):
        errors.append(
            _error(
                f"{field_prefix}.positive_prompt",
                "required_template_variable",
                "正提示词必须包含 {{域名}}",
            )
        )
    names = _variable_names(template.positive_prompt)
    for variable_name in ("域名", "用户参考要求"):
        count = names.count(variable_name)
        if count > 1:
            errors.append(
                _error(
                    f"{field_prefix}.positive_prompt",
                    "unknown_template_variable",
                    f"正提示词中的 {{{{{variable_name}}}}} 出现了 {count} 次，同一变量最多只能出现一次",
                )
            )
    errors.extend(_unknown_variable_errors(template.positive_prompt, f"{field_prefix}.positive_prompt"))
    errors.extend(_unknown_variable_errors(template.negative_prompt or "", f"{field_prefix}.negative_prompt"))
    return errors


def _is_structurally_complete_template(template: BatchPromptTemplateDto) -> bool:
    return bool(
        template.name.strip()
        and template.positive_prompt.strip()
        and "域名" in _variable_names(template.positive_prompt)
        and not _unknown_variable_errors(template.positive_prompt, "")
        and not _unknown_variable_errors(template.negative_prompt or "", "")
    )


def _variable_names(value: str) -> list[str]:
    return [match.group(1).strip() for match in _TEMPLATE_VARIABLE_PATTERN.finditer(value)]


def _unknown_variable_errors(value: str, field: str) -> list[StrategyValidationErrorDto]:
    return [
        _error(field, "unknown_template_variable", f"不支持变量 {{{{{name}}}}}")
        for name in _variable_names(value)
        if name not in {"域名", "用户参考要求"}
    ]


def _replace_variable(value: str, variable_name: str, replacement: str) -> str:
    return _TEMPLATE_VARIABLE_PATTERN.sub(
        lambda match: replacement if match.group(1).strip() == variable_name else match.group(0),
        value,
    )


def _compose_prompt(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"【{label}】\n{content.strip()}" for label, content in sections)


def _error(
    field: str,
    code: Literal[
        "required",
        "unknown_template_variable",
        "required_template_variable",
        "invalid_reference_image",
        "unverified_model_connection",
        "invalid_generation_count",
    ],
    message: str,
) -> StrategyValidationErrorDto:
    return StrategyValidationErrorDto(field=field, code=code, message=message)
