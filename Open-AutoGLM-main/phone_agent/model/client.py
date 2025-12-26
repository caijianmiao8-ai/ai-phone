"""Model client for AI inference using OpenAI-compatible API."""

import json
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from phone_agent.config.i18n import get_message


@dataclass
class ModelConfig:
    """Configuration for the AI model."""

    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    model_name: str = "autoglm-phone-9b"
    max_tokens: int = 3000
    temperature: float = 0.0
    top_p: float = 0.85
    frequency_penalty: float = 0.2
    extra_body: dict[str, Any] = field(default_factory=dict)
    lang: str = "cn"  # Language for UI messages: 'cn' or 'en'


@dataclass
class ModelResponse:
    """Response from the AI model."""

    thinking: str
    action: str
    raw_content: str
    # Performance metrics
    time_to_first_token: float | None = None  # Time to first token (seconds)
    time_to_thinking_end: float | None = None  # Time to thinking end (seconds)
    total_time: float | None = None  # Total inference time (seconds)


class ModelClient:
    """
    Client for interacting with OpenAI-compatible vision-language models.

    Args:
        config: Model configuration.
    """

    def __init__(self, config: ModelConfig | None = None):
        self.config = config or ModelConfig()
        self.client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key)

    def request(self, messages: list[dict[str, Any]]) -> ModelResponse:
        """
        Send a request to the model.

        Args:
            messages: List of message dictionaries in OpenAI format.

        Returns:
            ModelResponse containing thinking and action.

        Raises:
            ValueError: If the response cannot be parsed.
        """
        # Start timing
        start_time = time.time()
        time_to_first_token = None
        time_to_thinking_end = None

        stream = self.client.chat.completions.create(
            messages=messages,
            model=self.config.model_name,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            frequency_penalty=self.config.frequency_penalty,
            extra_body=self.config.extra_body,
            stream=True,
        )

        raw_content = ""
        buffer = ""  # Buffer to hold content that might be part of a marker
        # Standard markers + direct action names
        action_markers = ["finish(message=", "do(action="]
        # Add direct action patterns: Wait(, Tap(, Swipe(, etc.
        direct_action_patterns = [
            "Wait(", "Tap(", "Swipe(", "Type(", "Type_Name(",
            "Launch(", "Back(", "Home(", "Long Press(",
            "Double Tap(", "Take_over(", "Note(", "Call_API(", "Interact("
        ]
        all_markers = action_markers + direct_action_patterns
        in_action_phase = False  # Track if we've entered the action phase
        first_token_received = False

        for chunk in stream:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                raw_content += content

                # Record time to first token
                if not first_token_received:
                    time_to_first_token = time.time() - start_time
                    first_token_received = True

                if in_action_phase:
                    # Already in action phase, just accumulate content without printing
                    continue

                buffer += content

                # Check if any marker is fully present in buffer
                marker_found = False
                for marker in all_markers:
                    if marker in buffer:
                        # Marker found, print everything before it
                        thinking_part = buffer.split(marker, 1)[0]
                        print(thinking_part, end="", flush=True)
                        print()  # Print newline after thinking is complete
                        in_action_phase = True
                        marker_found = True

                        # Record time to thinking end
                        if time_to_thinking_end is None:
                            time_to_thinking_end = time.time() - start_time

                        break

                if marker_found:
                    continue  # Continue to collect remaining content

                # Check if buffer ends with a prefix of any marker
                # If so, don't print yet (wait for more content)
                is_potential_marker = False
                for marker in all_markers:
                    for i in range(1, len(marker)):
                        if buffer.endswith(marker[:i]):
                            is_potential_marker = True
                            break
                    if is_potential_marker:
                        break

                if not is_potential_marker:
                    # Safe to print the buffer
                    print(buffer, end="", flush=True)
                    buffer = ""

        # Calculate total time
        total_time = time.time() - start_time

        # Parse thinking and action from response
        thinking, action = self._parse_response(raw_content)

        # Print performance metrics
        lang = self.config.lang
        print()
        print("=" * 50)
        print(f"⏱️  {get_message('performance_metrics', lang)}:")
        print("-" * 50)
        if time_to_first_token is not None:
            print(
                f"{get_message('time_to_first_token', lang)}: {time_to_first_token:.3f}s"
            )
        if time_to_thinking_end is not None:
            print(
                f"{get_message('time_to_thinking_end', lang)}:        {time_to_thinking_end:.3f}s"
            )
        print(
            f"{get_message('total_inference_time', lang)}:          {total_time:.3f}s"
        )
        print("=" * 50)

        return ModelResponse(
            thinking=thinking,
            action=action,
            raw_content=raw_content,
            time_to_first_token=time_to_first_token,
            time_to_thinking_end=time_to_thinking_end,
            total_time=total_time,
        )

    def _parse_response(self, content: str) -> tuple[str, str]:
        """
        Parse the model response into thinking and action parts.

        Parsing rules:
        1. If content contains 'finish(message=', everything before is thinking,
           everything from 'finish(message=' onwards is action.
        2. If rule 1 doesn't apply but content contains 'do(action=',
           everything before is thinking, everything from 'do(action=' onwards is action.
        3. Fallback: If content contains '<answer>', use legacy parsing with XML tags.
        4. Otherwise, return empty thinking and full content as action.

        Args:
            content: Raw response content.

        Returns:
            Tuple of (thinking, action).
        """
        import re

        def clean_tags(text: str) -> str:
            """Remove XML tags from text."""
            text = text.replace("<think>", "").replace("</think>", "")
            text = text.replace("<answer>", "").replace("</answer>", "")
            text = text.replace("<action>", "").replace("</action>", "")
            return text.strip()

        # All supported action names that models might output directly
        DIRECT_ACTION_NAMES = [
            "Wait", "Tap", "Swipe", "Type", "Type_Name", "Launch",
            "Back", "Home", "Long Press", "Double Tap", "Take_over",
            "Note", "Call_API", "Interact"
        ]

        def extract_function_call(text: str, func_prefix: str) -> str:
            """Extract only the function call, ignoring any text after closing paren.

            For input like: '"Wait", duration="10 seconds")</answer>\n中文内容...'
            Returns: '"Wait", duration="10 seconds")'
            """
            # First clean XML tags
            text = clean_tags(text)

            # Find the matching closing parenthesis
            paren_count = 1  # We already have the opening paren from func_prefix
            end_pos = 0
            in_string = False
            string_char = None

            for i, char in enumerate(text):
                if in_string:
                    if char == string_char and (i == 0 or text[i-1] != '\\'):
                        in_string = False
                elif char in ('"', "'"):
                    in_string = True
                    string_char = char
                elif char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
                    if paren_count == 0:
                        end_pos = i + 1
                        break

            if end_pos > 0:
                return func_prefix + text[:end_pos]
            else:
                # Fallback: return cleaned text
                return func_prefix + text

        def find_direct_action_call(text: str) -> tuple[str, str, int] | None:
            """Find direct action calls like Wait(...), Tap(...) in text.

            Returns: (action_name, full_call, start_position) or None
            """
            # Build pattern to match direct action calls
            # Match: ActionName( or ActionName ( with optional space
            for action_name in DIRECT_ACTION_NAMES:
                # Pattern: action_name followed by ( with optional whitespace
                pattern = rf'\b{re.escape(action_name)}\s*\('
                match = re.search(pattern, text)
                if match:
                    start_pos = match.start()
                    # Extract the full function call starting from the match
                    remaining = text[match.end():]  # Text after opening paren

                    # Find matching closing paren
                    paren_count = 1
                    end_pos = 0
                    in_string = False
                    string_char = None

                    for i, char in enumerate(remaining):
                        if in_string:
                            if char == string_char and (i == 0 or remaining[i-1] != '\\'):
                                in_string = False
                        elif char in ('"', "'"):
                            in_string = True
                            string_char = char
                        elif char == '(':
                            paren_count += 1
                        elif char == ')':
                            paren_count -= 1
                            if paren_count == 0:
                                end_pos = i + 1
                                break

                    if end_pos > 0:
                        # Extract arguments part (inside parentheses)
                        args_part = remaining[:end_pos - 1]  # Exclude closing paren
                        full_call = f'{action_name}({args_part})'
                        return action_name, full_call, start_pos

            return None

        def convert_direct_action_to_do(action_name: str, full_call: str) -> str:
            """Convert direct action call to do(action=...) format.

            Example: Wait(duration="10 seconds") -> do(action="Wait", duration="10 seconds")
            """
            # Extract arguments from the call
            # full_call format: ActionName(arg1=val1, arg2=val2)
            open_paren = full_call.index('(')
            args_part = full_call[open_paren + 1:-1]  # Remove ActionName( and )

            if args_part.strip():
                return f'do(action="{action_name}", {args_part})'
            else:
                return f'do(action="{action_name}")'

        # Rule 1: Check for finish(message=
        if "finish(message=" in content:
            parts = content.split("finish(message=", 1)
            thinking = clean_tags(parts[0])
            action = extract_function_call(parts[1], "finish(message=")
            return thinking, action

        # Rule 2: Check for do(action=
        if "do(action=" in content:
            parts = content.split("do(action=", 1)
            thinking = clean_tags(parts[0])
            action = extract_function_call(parts[1], "do(action=")
            return thinking, action

        # Rule 3: Check for direct action calls like Wait(...), Tap(...), etc.
        # This handles models that don't use the do(action=...) wrapper
        direct_result = find_direct_action_call(content)
        if direct_result:
            action_name, full_call, start_pos = direct_result
            thinking = clean_tags(content[:start_pos])
            # Convert to standard do(action=...) format
            action = convert_direct_action_to_do(action_name, full_call)
            return thinking, action

        # Rule 4: Fallback to legacy XML tag parsing
        if "<answer>" in content:
            parts = content.split("<answer>", 1)
            thinking = clean_tags(parts[0])
            action = clean_tags(parts[1])
            # Try to extract function call from action
            if "do(action=" in action:
                action = extract_function_call(
                    action.split("do(action=", 1)[1], "do(action="
                )
            elif "finish(message=" in action:
                action = extract_function_call(
                    action.split("finish(message=", 1)[1], "finish(message="
                )
            else:
                # Check for direct action calls in the answer part
                direct_result = find_direct_action_call(action)
                if direct_result:
                    action_name, full_call, _ = direct_result
                    action = convert_direct_action_to_do(action_name, full_call)
            return thinking, action

        # Rule 5: No markers found, return content as action
        return "", content


class MessageBuilder:
    """Helper class for building conversation messages."""

    @staticmethod
    def create_system_message(content: str) -> dict[str, Any]:
        """Create a system message."""
        return {"role": "system", "content": content}

    @staticmethod
    def create_user_message(
        text: str, image_base64: str | None = None
    ) -> dict[str, Any]:
        """
        Create a user message with optional image.

        Args:
            text: Text content.
            image_base64: Optional base64-encoded image.

        Returns:
            Message dictionary.
        """
        content = []

        if image_base64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                }
            )

        content.append({"type": "text", "text": text})

        return {"role": "user", "content": content}

    @staticmethod
    def create_assistant_message(content: str) -> dict[str, Any]:
        """Create an assistant message."""
        return {"role": "assistant", "content": content}

    @staticmethod
    def remove_images_from_message(message: dict[str, Any]) -> dict[str, Any]:
        """
        Remove image content from a message to save context space.

        Args:
            message: Message dictionary.

        Returns:
            Message with images removed.
        """
        if isinstance(message.get("content"), list):
            message["content"] = [
                item for item in message["content"] if item.get("type") == "text"
            ]
        return message

    @staticmethod
    def build_screen_info(current_app: str, **extra_info) -> str:
        """
        Build screen info string for the model.

        Args:
            current_app: Current app name.
            **extra_info: Additional info to include.

        Returns:
            JSON string with screen info.
        """
        info = {"current_app": current_app, **extra_info}
        return json.dumps(info, ensure_ascii=False)
