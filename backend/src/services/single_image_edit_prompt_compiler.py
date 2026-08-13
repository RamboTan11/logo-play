"""Deterministic server-only compilation for single-image edit strategies."""

import re
from dataclasses import dataclass
from typing import Literal

from src.models.batch_generation_policy import StrategyValidationErrorDto
from src.models.single_image_edit_policy import SingleImageEditPolicyPayload

SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION = "logo-prompt-compiler-v4"
SINGLE_IMAGE_EDIT_RULE_SET_VERSION = "single-edit-delta-v1"
SINGLE_IMAGE_EDIT_OUTPUT_CONSTRAINT = (
    "输出 1 张完整、清晰、适合品牌交付的 Logo 图片；"
    "不得输出多图拼版、解释文字或供应商参数。"
)

_TEMPLATE_VARIABLE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
_USER_DESCRIPTION_VARIABLE = "用户补充描述"
_EDIT_INSTRUCTION_VARIABLE = "用户修改指令"
SINGLE_EDIT_RULE_BLOCKS = (
    ("named-change-scope", "只允许修改修改指令明确点名的部分。"),
    ("preserve-unspecified", "未点名的文字、图标、构图、颜色、比例及核心品牌识别元素保持不变。"),
    ("conflict-resolution", "用户点名部分优先采用用户要求，其余部分继续受保留规则约束。"),
    (
        "prohibited-default-transformations",
        "无明确要求时禁止整体重绘、品牌重塑、改字、改构图或配色，以及 3D 样机化。",
    ),
)


@dataclass(frozen=True, slots=True)
class SingleImageEditCompileContext:
    """Database facts required to validate a policy without provider configuration."""

    model_connection_id: str | None
    model_connection_version: int | None
    image_to_image_verified: bool


@dataclass(frozen=True, slots=True)
class SingleImageEditPromptCompilation:
    """Internal runtime input consumed by T-014, never exposed by a preview API."""

    compiled_prompt: str
    compiler_version: str
    output_constraint: str
    rule_blocks: tuple[tuple[str, str], ...]


class SingleImageEditPromptCompilationError(ValueError):
    """A structured internal compile failure for future generation orchestration."""

    def __init__(self, validation_errors: list[StrategyValidationErrorDto]) -> None:
        super().__init__("single_image_edit_prompt_compilation_failed")
        self.validation_errors = validation_errors


def validate_single_image_edit_policy(
    policy: SingleImageEditPolicyPayload,
    context: SingleImageEditCompileContext,
) -> list[StrategyValidationErrorDto]:
    """Return field errors without changing a browser's unpublished draft."""

    errors: list[StrategyValidationErrorDto] = []
    if (
        not policy.model_connection_id
        or policy.model_connection_id != context.model_connection_id
        or not context.image_to_image_verified
    ):
        errors.append(
            _error(
                "model_connection_id",
                "unverified_model_connection",
                "请选择已通过图生图能力测试的模型连接",
            )
        )
    if not policy.positive_content.strip():
        errors.append(_error("positive_content", "required", "请填写正向内容"))
    elif _EDIT_INSTRUCTION_VARIABLE not in _variable_names(policy.positive_content):
        errors.append(
            _error(
                "positive_content",
                "required_template_variable",
                "正向内容必须包含 {{用户修改指令}}",
            )
        )
    errors.extend(
        _variable_errors(
            policy.positive_content,
            "positive_content",
            allowed={_EDIT_INSTRUCTION_VARIABLE},
        )
    )
    errors.extend(_variable_errors(policy.negative_avoidance, "negative_avoidance", allowed=set()))
    return errors


def compile_single_image_edit_prompt(
    *,
    policy: SingleImageEditPolicyPayload,
    context: SingleImageEditCompileContext,
    edit_instruction: str | None = None,
    user_description: str | None = None,
) -> SingleImageEditPromptCompilation:
    """Compile the fixed single-image prompt blocks in their canonical order.

    The customer description is replaced directly inside the positive content.
    Source-image selection belongs to T-014 and does not inject creative Prompt text.
    """

    errors = validate_single_image_edit_policy(policy, context)
    if errors:
        raise SingleImageEditPromptCompilationError(errors)
    instruction = (edit_instruction if edit_instruction is not None else user_description or "").strip()
    sections = [("正向内容", _replace_edit_instruction(policy.positive_content, instruction))]
    sections.extend(SINGLE_EDIT_RULE_BLOCKS)
    if policy.negative_avoidance.strip():
        sections.append(("负向避免项", policy.negative_avoidance))
    sections.append(("输出约束", SINGLE_IMAGE_EDIT_OUTPUT_CONSTRAINT))
    return SingleImageEditPromptCompilation(
        compiled_prompt=_compose_prompt(sections),
        compiler_version=SINGLE_IMAGE_EDIT_PROMPT_COMPILER_VERSION,
        output_constraint=SINGLE_IMAGE_EDIT_OUTPUT_CONSTRAINT,
        rule_blocks=SINGLE_EDIT_RULE_BLOCKS,
    )


def _variable_names(value: str) -> list[str]:
    return [match.group(1).strip() for match in _TEMPLATE_VARIABLE_PATTERN.finditer(value)]


def _variable_errors(
    value: str,
    field: str,
    *,
    allowed: set[str],
) -> list[StrategyValidationErrorDto]:
    return [
        _error(field, "unknown_template_variable", f"不支持变量 {{{{{name}}}}}")
        for name in _variable_names(value)
        if name not in allowed
    ]


def _replace_edit_instruction(value: str, instruction: str) -> str:
    return _TEMPLATE_VARIABLE_PATTERN.sub(
        lambda match: instruction if match.group(1).strip() == _EDIT_INSTRUCTION_VARIABLE else match.group(0),
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
        "unverified_model_connection",
    ],
    message: str,
) -> StrategyValidationErrorDto:
    return StrategyValidationErrorDto(field=field, code=code, message=message)
