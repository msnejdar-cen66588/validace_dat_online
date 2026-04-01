"""Unified LLM client to support both Gemini and OpenAI providers."""
import json
import asyncio
import os
import base64
from typing import Optional, List, Any, Union
import httpx
from config import GEMINI_API_KEY, GEMINI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

class LLMClient:
    """Unified client for interacting with different LLM providers."""

    def __init__(self, model_name: str = "gemini"):
        self.model_name = model_name.lower()
        self.gemini_client = None
        
        if self._is_gemini():
            if GEMINI_API_KEY:
                from google import genai
                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        else:
            # Any non-Gemini model goes through OpenAI-compatible endpoint
            self.openai_api_key = OPENAI_API_KEY
            self.openai_base_url = OPENAI_BASE_URL
            # Use the exact model name provided (e.g. gpt-4o, gpt-4o-mini, o3-mini)
            self.openai_model = self.model_name if self.model_name != "openai" else OPENAI_MODEL

    def _is_gemini(self) -> bool:
        return "gemini" in self.model_name

    async def generate_content(
        self,
        system_instruction: str,
        contents: Union[str, List[Any]],
        response_mime_type: str = "text/plain",
        max_output_tokens: int = 2048,
        temperature: float = 0.7
    ) -> str:
        """Generate content from the selected LLM provider."""
        # Normalize contents to a list
        if isinstance(contents, str) or not isinstance(contents, list):
            contents = [contents]

        if self._is_gemini():
            return await self._generate_gemini(
                system_instruction, contents, response_mime_type, max_output_tokens, temperature
            )
        else:
            return await self._generate_openai_compatible(
                system_instruction, contents, response_mime_type, max_output_tokens, temperature
            )

    async def _generate_gemini(
        self,
        system_instruction: str,
        contents: List[Any],
        response_mime_type: str,
        max_output_tokens: int,
        temperature: float
    ) -> str:
        if not self.gemini_client:
            raise ValueError("Gemini client not initialized (check API key)")

        from google.genai import types

        # Normalize content parts: convert generic image objects to Gemini Part objects
        normalized = []
        for part in contents:
            if isinstance(part, str):
                normalized.append(part)
            elif hasattr(part, "inline_data"):
                # Already a Gemini Part object
                normalized.append(part)
            elif hasattr(part, "data") and hasattr(part, "mime_type"):
                # Generic image container — convert to Gemini Part
                normalized.append(
                    types.Part.from_bytes(data=part.data, mime_type=part.mime_type)
                )
            else:
                normalized.append(str(part))
        
        # Determine the model string to use
        model = self.model_name if self.model_name != "gemini" else GEMINI_MODEL

        response = await self.gemini_client.aio.models.generate_content(
            model=model,
            contents=normalized,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type=response_mime_type,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
        )
        return response.text

    async def _generate_openai_compatible(
        self,
        system_instruction: str,
        contents: List[Any],
        response_mime_type: str,
        max_output_tokens: int,
        temperature: float
    ) -> str:
        """Call an OpenAI-compatible API gateway with enhanced robustness."""
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not provided")

        messages = [{"role": "system", "content": system_instruction}]
        
        user_content = []
        for part in contents:
            if isinstance(part, str):
                user_content.append({"type": "text", "text": part})
            elif hasattr(part, "inline_data") and part.inline_data: # Gemini Part object from SDK
                encoded = base64.b64encode(part.inline_data.data).decode('utf-8')
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.inline_data.mime_type};base64,{encoded}"}
                })
            elif hasattr(part, "data") and hasattr(part, "mime_type"): # Fallback for other Part-like objects
                encoded = base64.b64encode(part.data).decode('utf-8')
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{part.mime_type};base64,{encoded}"}
                })
            else:
                user_content.append({"type": "text", "text": str(part)})
        
        # Simplify user content if only one text part is present (more compatible with older gateways)
        if len(user_content) == 1 and user_content[0]["type"] == "text":
            user_content_payload = user_content[0]["text"]
        else:
            user_content_payload = user_content

        # o-series reasoning models don't support system role or temperature
        is_reasoning = self.openai_model.startswith("o1") or self.openai_model.startswith("o3") or self.openai_model.startswith("o4")

        if is_reasoning:
            # Reasoning models: system instructions go as user message
            messages = [{"role": "user", "content": f"Instructions: {system_instruction}\n\n{user_content_payload if isinstance(user_content_payload, str) else ''}"}]
            if not isinstance(user_content_payload, str):
                messages.append({"role": "user", "content": user_content_payload})
        else:
            messages.append({"role": "user", "content": user_content_payload})

        # Newer models (gpt-5.x, gpt-4.1, o-series) require max_completion_tokens
        uses_new_api = any(self.openai_model.startswith(p) for p in ["gpt-5", "gpt-4.1", "o1", "o3", "o4"])

        payload = {
            "model": self.openai_model,
            "messages": messages,
        }

        if uses_new_api:
            payload["max_completion_tokens"] = max_output_tokens
        else:
            payload["max_tokens"] = max_output_tokens

        if not is_reasoning:
            payload["temperature"] = temperature
        
        # Only use json_object if explicitly requested
        if response_mime_type == "application/json":
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }

        verify_ssl = os.getenv("VERIFY_SSL", "true").lower() == "true"
        url = f"{self.openai_base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=120.0, verify=verify_ssl, http2=False) as client:
            max_retries = 4
            last_err = None
            
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        print(f"DEBUG: Retrying OpenAI request (attempt {attempt+1})...")

                    print(f"DEBUG: Calling OpenAI at {url} | Model: {self.openai_model}")
                    
                    response = await client.post(
                        url,
                        headers=headers,
                        json=payload
                    )
                    
                    # Handle 429 rate limit with exponential backoff
                    if response.status_code == 429:
                        retry_after = response.headers.get("retry-after")
                        if retry_after:
                            wait = min(float(retry_after), 60)
                        else:
                            wait = min(5 * (2 ** attempt), 60)  # 5s, 10s, 20s, 40s, 60s
                        print(f"DEBUG: Rate limited (429), waiting {wait}s before retry...")
                        await asyncio.sleep(wait)
                        continue
                    
                    if response.status_code != 200:
                        print(f"DEBUG: OpenAI Error {response.status_code}: {response.text[:300]}")
                    
                    response.raise_for_status()
                    result = response.json()
                    return result["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        # Already handled above, but just in case
                        wait = min(5 * (2 ** attempt), 60)
                        print(f"DEBUG: Rate limited (429 exception), waiting {wait}s...")
                        await asyncio.sleep(wait)
                        last_err = e
                    else:
                        print(f"DEBUG: Attempt {attempt+1} failed: {str(e)}")
                        last_err = e
                        break  # Non-rate-limit errors should not retry
                except Exception as e:
                    print(f"DEBUG: Attempt {attempt+1} failed: {str(e)}")
                    last_err = e
                    if attempt < max_retries:
                        await asyncio.sleep(2)
            
            print(f"DEBUG: All {max_retries+1} attempts failed.")
            raise last_err
