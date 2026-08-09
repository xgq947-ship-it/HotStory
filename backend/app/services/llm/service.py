from __future__ import annotations

import asyncio
import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models import LLMCall
from app.services.artifacts import ProjectStore
from app.services.llm.provider import LLMProvider, LLMResponse
from app.utils import describe_error, new_id, sha256_text, stable_json

T = TypeVar("T", bound=BaseModel)


def parse_json_content(content: str) -> dict | list:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        object_start = stripped.find("{")
        array_start = stripped.find("[")
        starts = [index for index in (object_start, array_start) if index >= 0]
        if not starts:
            raise
        start = min(starts)
        end = stripped.rfind("}" if stripped[start] == "{" else "]")
        if end <= start:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, (dict, list)):
        raise ValueError("LLM JSON 顶层必须是对象或数组")
    return value


class LLMService:
    def __init__(self, provider: LLMProvider, store: ProjectStore | None = None) -> None:
        self.provider = provider
        self.store = store or ProjectStore()
        self._record_lock = asyncio.Lock()

    def _record(
        self,
        session: Session,
        topic_id: str,
        step: str,
        prompt: str,
        response: LLMResponse | None,
        parsed: dict | list | None = None,
        error: str | None = None,
    ) -> tuple[str, dict]:
        call_id = new_id("llm")
        raw_content = response.content if response else ""
        call = LLMCall(
            id=call_id,
            topic_id=topic_id,
            step=step,
            provider=response.provider if response else self.provider.name,
            model=response.model if response else self.provider.model,
            prompt_hash=sha256_text(prompt),
            raw_response=raw_content,
            parsed_json=parsed,
            status="FAILED" if error else "SUCCESS",
            error=error,
        )
        session.add(call)
        session.flush()
        return call_id, {
            "id": call_id,
            "step": step,
            "provider": call.provider,
            "model": call.model,
            "prompt_hash": call.prompt_hash,
            "raw_response": raw_content,
            "parsed": parsed,
            "error": error,
        }

    async def _record_and_commit(
        self,
        session: Session,
        topic_id: str,
        step: str,
        prompt: str,
        response: LLMResponse | None,
        parsed: dict | list | None = None,
        error: str | None = None,
    ) -> None:
        # Provider calls may run concurrently, but one SQLAlchemy Session must
        # never be flushed by two asyncio tasks at the same time.
        async with self._record_lock:
            try:
                call_id, payload = self._record(
                    session,
                    topic_id,
                    step,
                    prompt,
                    response,
                    parsed=parsed,
                    error=error,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        # 落盘（json.dumps + fsync）在锁外、线程里做，不占事件循环。
        await self.store.save_json_file_async(topic_id, f"llm_raw/{call_id}", payload)

    async def generate_model(
        self,
        session: Session,
        topic_id: str,
        step: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        schema = stable_json(response_model.model_json_schema())
        full_prompt = f"{user_prompt}\n\n请严格返回 JSON，JSON Schema：\n{schema}"
        response: LLMResponse | None = None
        try:
            response = await self.provider.generate_json(system_prompt, full_prompt)
            parsed = parse_json_content(response.content)
            validated = response_model.model_validate(parsed)
            await self._record_and_commit(
                session, topic_id, step, full_prompt, response, parsed=parsed
            )
            return validated
        except (json.JSONDecodeError, ValueError, ValidationError) as first_error:
            await self._record_and_commit(
                session,
                topic_id,
                f"{step}:invalid_json",
                full_prompt,
                response,
                error=str(first_error),
            )
            repair_prompt = (
                "修复下面内容，使其严格符合给定 JSON Schema。不得添加解释或代码围栏。\n\n"
                f"JSON Schema：{schema}\n\n待修复内容：\n{response.content if response else ''}"
            )
            repaired: LLMResponse | None = None
            try:
                repaired = await self.provider.generate_json(
                    "你是严格 JSON 修复器。只能修复格式，不得创造新的现实事实。", repair_prompt
                )
                parsed = parse_json_content(repaired.content)
                validated = response_model.model_validate(parsed)
                await self._record_and_commit(
                    session,
                    topic_id,
                    f"{step}:repair",
                    repair_prompt,
                    repaired,
                    parsed=parsed,
                )
                return validated
            except Exception as repair_error:
                await self._record_and_commit(
                    session,
                    topic_id,
                    f"{step}:repair_failed",
                    repair_prompt,
                    repaired,
                    error=str(repair_error),
                )
                raise RuntimeError(f"LLM JSON 校验失败：{repair_error}") from repair_error
        except Exception as error:
            await self._record_and_commit(
                session, topic_id, step, full_prompt, response, error=describe_error(error)
            )
            raise

    async def generate_text(
        self,
        session: Session,
        topic_id: str,
        step: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        response: LLMResponse | None = None
        try:
            response = await self.provider.generate_text(system_prompt, user_prompt)
            await self._record_and_commit(session, topic_id, step, user_prompt, response)
            return response.content
        except Exception as error:
            await self._record_and_commit(
                session, topic_id, step, user_prompt, response, error=describe_error(error)
            )
            raise
