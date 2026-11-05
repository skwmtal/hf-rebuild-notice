"""선택 기능: ANTHROPIC_API_KEY가 있을 때 규칙 기반 안내문을 쉬운 문장으로 다듬는다."""
import anthropic

SYSTEM = (
    "고령 주택연금 가입자에게 보내는 안내문을 더 쉬운 말로 다듬는다. "
    "주어진 안내문에 있는 사실, 제도, 숫자만 쓰고 새로운 내용은 더하지 않는다. "
    "각 항목의 '근거' 표시는 그대로 남긴다."
)


def polish(text: str) -> str:
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=4000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    if response.stop_reason == "refusal":
        return text
    return "".join(b.text for b in response.content if b.type == "text") or text
