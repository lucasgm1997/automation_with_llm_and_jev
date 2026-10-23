"""Adapt OpenAI Decisions to the executor's bounded action contract."""

import json
import math
import os

import httpx

from .policy import ACTION_INSTRUCTIONS, DEFAULT_MODELS
from .semantics import RunStopped


class OpenAIDecisionsPolicy:
    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str = DEFAULT_MODELS["openai"],
        api_key: str | None = None,
    ):
        if model != DEFAULT_MODELS["openai"]:
            raise ValueError("OpenAI Decisions currently supports model gpt-6-luna only.")
        self.client = client
        self.model = model
        self.actual_model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Set OPENAI_API_KEY in automation/.env or the local environment."
            )

    async def choose(self, state: dict, actions: dict) -> dict:
        try:
            response = await self.client.post(
                "https://api.openai.com/v1/decisions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "input": [{
                        "role": "user",
                        "content": [{"type": "input_json", "data": state}],
                    }],
                    "questions": [{
                        "type": "choice",
                        "name": "next_action",
                        "instructions": ACTION_INSTRUCTIONS,
                        "choices": [
                            {"value": key, "description": json.dumps(action, ensure_ascii=False)}
                            for key, action in actions.items()
                        ],
                    }],
                },
            )
        except httpx.RequestError as exc:
            # Do not copy headers, inputs, or response bodies into the trace.
            raise RuntimeError(
                f"OpenAI Decisions request failed ({type(exc).__name__})."
            ) from None
        if response.is_error:
            raise RuntimeError(f"OpenAI Decisions API returned HTTP {response.status_code}.")

        try:
            payload = response.json()
            model = payload["model"]
            if not isinstance(model, str) or not model:
                raise ValueError
            self.actual_model = model
            answers = payload["answers"]
            if not isinstance(answers, list) or len(answers) != 1:
                raise ValueError
            answer = answers[0]
            if answer["name"] != "next_action":
                raise ValueError
            if answer["type"] == "refusal":
                raise RunStopped("OpenAI Decisions refused to choose an action.")
            if answer["type"] != "choice":
                raise ValueError
            probabilities = {}
            for entry in answer["probabilities"]:
                value, probability = entry["value"], entry["probability"]
                if (
                    not isinstance(value, str) or value not in actions or value in probabilities
                    or isinstance(probability, bool) or not isinstance(probability, (int, float))
                    or not math.isfinite(probability) or not 0 <= probability <= 1
                ):
                    raise ValueError
                probabilities[value] = probability
            if probabilities.keys() != actions.keys():
                raise ValueError
            # UIRunner validates action membership and confidence before any UI action.
            # Confidence is supplied by Decisions, never inferred from probabilities.
            return {
                "action": answer["choice"],
                "confidence": answer["confidence"],
                "probabilities": probabilities,
            }
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("OpenAI Decisions returned an invalid response.") from None
