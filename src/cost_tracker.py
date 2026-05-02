import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Gemini 料金 (per 1M tokens, USD)
_GEMINI_PRICES = {
    "gemini-2.0-flash":       {"input": 0.075,  "output": 0.30},
    "gemini-2.0-flash-lite":  {"input": 0.0375, "output": 0.15},
    "gemini-2.5-flash":       {"input": 0.075,  "output": 0.30},
    "gemini-2.5-pro":         {"input": 1.25,   "output": 10.00},
    "gemini-1.5-pro":         {"input": 1.25,   "output": 5.00},
    "gemini-1.5-flash":       {"input": 0.075,  "output": 0.30},
}
_WHISPER_API_PER_MIN = 0.006  # OpenAI Whisper API (USD/分)
_USD_TO_JPY = 155.0


@dataclass
class CostEntry:
    label: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_sec: float = 0.0  # Whisper API用
    cost_usd: float = 0.0


class CostTracker:
    """API呼び出しごとのトークン数・コストを記録し最後に集計出力する"""

    def __init__(self):
        self._entries: List[CostEntry] = []

    def record_gemini(self, label: str, model: str, response):
        """Gemini APIレスポンスからトークン数・コストを記録"""
        try:
            usage = response.usage_metadata
            in_t = getattr(usage, "prompt_token_count", 0) or 0
            out_t = getattr(usage, "candidates_token_count", 0) or 0
        except Exception:
            in_t, out_t = 0, 0

        price = _GEMINI_PRICES.get(model, _GEMINI_PRICES["gemini-2.0-flash"])
        cost = (in_t * price["input"] + out_t * price["output"]) / 1_000_000

        entry = CostEntry(label=label, model=model,
                          input_tokens=in_t, output_tokens=out_t, cost_usd=cost)
        self._entries.append(entry)
        logger.debug(f"[cost] {label}: in={in_t:,} out={out_t:,} ${cost:.5f}")

    def record_whisper_api(self, label: str, duration_sec: float):
        """OpenAI Whisper APIのコストを記録"""
        cost = (duration_sec / 60.0) * _WHISPER_API_PER_MIN
        entry = CostEntry(label=label, model="whisper-1",
                          duration_sec=duration_sec, cost_usd=cost)
        self._entries.append(entry)
        logger.debug(f"[cost] {label}: {duration_sec:.0f}sec ${cost:.5f}")

    def summary(self) -> str:
        """コスト集計を文字列で返す（ログ・通知用）"""
        if not self._entries:
            return "API使用なし (無料)"

        lines = []
        lines.append("=" * 48)
        lines.append("  API使用コスト内訳")
        lines.append("=" * 48)

        total_usd = 0.0
        for e in self._entries:
            total_usd += e.cost_usd
            if e.model == "whisper-1":
                lines.append(
                    f"  {e.label:<22} {e.duration_sec:>5.0f}sec"
                    f"  ${e.cost_usd:.4f}  ({e.cost_usd * _USD_TO_JPY:.2f}円)"
                )
            else:
                lines.append(
                    f"  {e.label:<22} in:{e.input_tokens:>6,} out:{e.output_tokens:>5,}"
                    f"  ${e.cost_usd:.4f}  ({e.cost_usd * _USD_TO_JPY:.2f}円)"
                )

        total_jpy = total_usd * _USD_TO_JPY
        lines.append("-" * 48)
        lines.append(f"  合計                       ${total_usd:.4f}  ({total_jpy:.2f}円)")
        lines.append("=" * 48)
        return "\n".join(lines)

    def print_summary(self):
        print(self.summary())
        logger.info(self.summary())

    def total_usd(self) -> float:
        return sum(e.cost_usd for e in self._entries)


# プロセス内シングルトン
_tracker: Optional[CostTracker] = None


def get_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker


def reset_tracker():
    global _tracker
    _tracker = CostTracker()
