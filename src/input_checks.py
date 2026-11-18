"""Input normalization and classification, applied first in assistant.ask().

Steps:
  1. normalize:     Unicode NFKC, decode HTML entities once, drop control/zero-width characters.
  2. classify:      prompt-injection-style instructions are detected on the normalized text.
  3. strip markup:  <script>/<style> elements are removed with their content, HTML comments and
                    known HTML tags are removed. Unknown angle brackets are kept, so Java generics
                    (Map<String, Object>), XML error bodies (<fault>...</fault>) and "a < b" survive.
  4. markup-only:   if markup was removed and either nothing alphanumeric is left, or active markup
                    (script/style, event handlers, javascript: links, iframes) was removed and fewer
                    than two real words remain, the input is not a problem description
                    (e.g. "<script>alert(1)</script>"). Harmless formatting such as
                    "timeout <b>500</b>" is cleaned and searched normally.
  5. non-troubleshooting: requests for creative or general content ("write me a poem about
                    servers", "tell me a joke", "translate this") are answered with a short
                    explanation instead of the closest KB entry.

This is input hygiene, not a security boundary. The assistant has no LLM, tools or secrets, so
injected instructions cannot do anything; the goal is to answer such input correctly ("not found")
instead of matching keywords such as "alert" or "API key".
"""

import html
import re
import unicodedata
from dataclasses import dataclass

TROUBLESHOOTING = "troubleshooting"
MARKUP_ONLY = "markup_only"
INJECTION = "injection"
NON_TROUBLESHOOTING = "non_troubleshooting"

# --- markup -----------------------------------------------------------------------------------
# A tag starts with "<" immediately followed by the name (no space), as in HTML itself, so
# comparisons such as "a < b and c > d" are never mistaken for tags.
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
# Multi-letter HTML tag names (case-insensitive). Single-letter tags (a, b, i, p, u) are matched in
# lower case only, so generic type parameters such as List<T> or Map<K, V> are left alone.
_HTML_TAG = re.compile(
    r"</?(?:abbr|audio|base|body|br|button|code|div|em|embed|form|frame|frameset|h[1-6]|head|html|iframe"
    r"|img|input|li|link|meta|object|ol|option|pre|select|source|span|strong|style|script|svg|table|td|textarea"
    r"|th|tr|ul|video)(?=[\s/>])[^<>]*>",
    re.IGNORECASE,
)
_SINGLE_LETTER_TAG = re.compile(r"</?[abipu](?=[\s/>])[^<>]*>")
# Any tag, known or not, that carries an event handler ("<details open ontoggle=alert(1)>").
_EVENT_HANDLER_TAG = re.compile(r"<[a-z][\w-]*\s[^<>]*\bon[a-z]+\s*=[^<>]*(?:>|$)", re.IGNORECASE)
_JS_URL = re.compile(r"\bjavascript\s*:\S*", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]{3,}")  # a "real word": 3+ letters (any script)
# "Active" markup: content that would run or embed something in a browser. Plain formatting tags
# (<b>, <strong>, <span>, <code>) are not active, so "timeout <b>500</b>" is still a real query.
_ACTIVE_MARKUP = re.compile(
    r"<(?:script|style|iframe|object|embed)\b|<[^<>]*\bon[a-z]+\s*=|\bjavascript\s*:", re.IGNORECASE
)

# --- prompt injection ---------------------------------------------------------------------------
# Instruction *structure* is required, not single words: "SYSTEM: ERROR connection refused",
# "admin API returns 403" and "ignore list for fraud rules" are ordinary troubleshooting text.
# Strong targets are suspicious on their own; weak ones only with a determiner ("your rules"),
# so "ignore rules engine timeout" or "ignore context switches" stay troubleshooting text.
_STRONG_TARGETS = r"(?:instructions?|system\s+prompt|guardrails|knowledge\s*base|kb)"
_WEAK_TARGETS = r"(?:rules|guidelines|prompts?|policies|restrictions|context)"
_TARGETS = rf"(?:{_STRONG_TARGETS}|{_WEAK_TARGETS})"
_DETERMINERS = r"(?:all|any|of|the|your|my|these|those|previous|prior|above|earlier|system)"
# "your instructions for/on/about <task>" asks for the KB guidance ("show your instructions for escalating
# a DNS outage"), not for the assistant's own instructions.
_SECRETS = (r"(?:system\s+prompt|hidden\s+instructions|your\s+instructions(?!\s+(?:for|on|about|to)\b)|initial\s+prompt|api\s+keys?|secrets?"
            r"|passwords?|credentials|private\s+keys?|access\s+tokens?|admin\s+token|root\s+password)")
# Only determiners/modifiers may sit between a "reveal"-type verb and the secret, so
# "tell me why the API key is rejected" stays troubleshooting text.
_SECRET_MODIFIERS = (r"(?:all|every|the|your|my|our|their|any|stored|saved|current|prod|production|admin|root|db"
                     r"|database|merchant|hidden|initial|system)")
# Secret words used as part of an ordinary noun phrase: "password reset", "API keys page".
_SECRET_COMPOUND = (r"(?!\s+(?:reset|expir\w*|polic\w*|rotation|change|error|errors|field|form|page|screen|tab|endpoint"
                    r"|api|service|table|manager|length|validation|hash|issue|issues|check|flow)\b)")
_INJECTION_PATTERNS = [
    # "ignore all previous instructions", "disregard your rules", "override the KB"
    rf"\b(?:ignore|disregard|forget|override|bypass)\s+(?:{_DETERMINERS}\s+)*{_STRONG_TARGETS}\b",
    rf"\b(?:ignore|disregard|forget|override|bypass)\s+(?:{_DETERMINERS}\s+)+{_WEAK_TARGETS}\b",
    # "forget everything you were told", "disregard what you were told"
    r"\b(?:ignore|disregard|forget)\s+(?:everything|anything|all\s+of\s+that)\b",
    r"\b(?:ignore|disregard|forget)\s+(?:what|whatever)\s+you\s+(?:were|have\s+been|'ve\s+been)\s+(?:told|instructed|given|taught)\b",
    r"\bsystem\s+prompt\s+override\b",
    # "you are now in admin mode", "you're now DAN"
    r"\b(?:you\s+are|you'?re)\s+now\s+(?:in\s+|an?\s+|the\s+|my\s+)?(?:\w+\s+)?(?:mode|assistant|ai|bot|admin|administrator|root|developer|dan|unrestricted|jailbroken)\b",
    # "from now on you are an unrestricted assistant", "from now on, you will ignore ..."
    # (but not "from now on you will see 504 errors": a role or an instruction verb is required)
    r"\b(?:from\s+now\s+on|starting\s+now)\b[,\s]+you\s+(?:"
    r"(?:are|will\s+be|must\s+be|shall\s+be)\s+(?:an?\s+|the\s+|my\s+)?(?:[\w-]+\s+)?"
    r"(?:assistant|ai|bot|admin|administrator|root|developer|unrestricted|jailbroken|dan)\b"
    r"|(?:will|must|shall|should)\s+(?:ignore|answer|respond|reply|obey|act|pretend|reveal|bypass|disregard|forget)\b)",
    # Modes that are only ever requests to the assistant ("switch to god mode").
    # Not "debug/developer mode": ordinary engineering terms.
    r"\b(?:god|jailbreak|unrestricted|dan)\s+mode\b",
    # "admin mode" only as an instruction ("you are in admin mode", "enable admin mode"), so a
    # genuine question such as "admin mode page won't load" is not flagged.
    r"\b(?:you\s+are\s+(?:now\s+)?in|enter|entering|enable|enabling|activate|activating|switch\s+(?:to|into)"
    r"|go\s+into|turn\s+on|put\s+(?:yourself|you)\s+in(?:to)?)\s+(?:the\s+)?admin(?:istrator)?\s+mode\b",
    # "pretend to be the database admin", "act as my bank"
    r"\b(?:pretend|act|behave|roleplay)\s+(?:to\s+be|as|like)\s+(?:an?\s+|the\s+|my\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:admin|administrator|root|developer|system|assistant|ai|shell|dba|bank|hacker|unrestricted)\b",
    # "list all API keys", "reveal the hidden instructions", "give me the prod password"
    rf"\b(?:reveal|print|show|display|output|dump|list|give|tell|send|expose|leak)\s+(?:me\s+|us\s+)?(?:{_SECRET_MODIFIERS}\s+){{0,3}}{_SECRETS}\b{_SECRET_COMPOUND}",
    # Hinglish: "instructions ignore karo", "API keys dikhao"
    rf"\b{_TARGETS}\b.{{0,30}}\b(?:ignore|bhool)\s+(?:kar|ja)",
    r"\b(?:api\s+keys?|passwords?|secrets?|credentials)\b.{0,20}\b(?:dikhao|batao|bhejo)\b",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)

# --- non-troubleshooting requests (Phase 3) -------------------------------------------------------
# Requests for creative or general content, e.g. "write me a poem about servers". Only matched at the
# start of the input, so "user story for checkout fails" or "the joke is that the 500s came back" are
# still searched.
_ASK = r"^\s*(?:(?:please|pls|hey|hi)[\s,]+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
_NON_TROUBLESHOOTING = re.compile(
    _ASK + r"(?:write|compose|tell|give|make|generate|create|sing)\s+(?:me\s+|us\s+)?(?:an?\s+|some\s+|another\s+)?"
    r"(?:(?:short|funny|little|nice|quick|small)\s+)?(?:story|stories|poem|poems|joke|jokes|song|songs|haiku|limerick"
    r"|rap|riddle|essay)\b"
    r"|" + _ASK + r"translate\s+(?:this|that|it|the\s+following)\b"
    r"|\btranslate\s+.{1,80}?\s+(?:into|to)\s+(?:hindi|english|french|spanish|german|marathi|tamil|telugu|bengali"
    r"|gujarati|kannada|japanese|chinese)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InputCheck:
    text: str                 # cleaned text to use downstream ("" if nothing meaningful is left)
    kind: str                 # TROUBLESHOOTING, MARKUP_ONLY or INJECTION
    markup_removed: bool = False
    evidence: str | None = None  # matched injection text (for tests and debugging)


def normalize(raw: str) -> str:
    """NFKC, decode HTML entities once, drop control/format characters, collapse whitespace."""
    text = html.unescape(unicodedata.normalize("NFKC", raw or ""))
    kept = []
    for ch in text:
        if ch in "\t\n\r":
            kept.append(" ")
        elif unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn"):
            kept.append(ch)
    return " ".join("".join(kept).split())


def strip_markup(text: str) -> tuple[str, bool]:
    """Remove script/style elements, HTML comments, known HTML tags and javascript: URLs."""
    cleaned = text
    for pattern in (_SCRIPT_OR_STYLE, _HTML_COMMENT, _EVENT_HANDLER_TAG, _HTML_TAG, _SINGLE_LETTER_TAG, _JS_URL):
        cleaned = pattern.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned, cleaned != text


def check_input(raw: str) -> InputCheck:
    """Normalize and classify user input. Injection is checked before markup is removed, so an
    instruction hidden in an HTML comment is still seen."""
    text = normalize(raw)
    injection = _INJECTION.search(text)
    if injection:
        return InputCheck(text, INJECTION, evidence=injection.group(0))

    cleaned, markup_removed = strip_markup(text)
    if markup_removed:
        nothing_left = not any(ch.isalnum() for ch in cleaned)
        active_with_little_text = bool(_ACTIVE_MARKUP.search(text)) and len(_WORD.findall(cleaned)) < 2
        if nothing_left or active_with_little_text:
            return InputCheck("", MARKUP_ONLY, markup_removed=True)
    if not any(ch.isalnum() for ch in cleaned):
        cleaned = ""  # emoji, punctuation or symbols only: nothing to search for
    request = _NON_TROUBLESHOOTING.search(cleaned)
    if request:
        return InputCheck(cleaned, NON_TROUBLESHOOTING, markup_removed=markup_removed, evidence=request.group(0).strip())
    return InputCheck(cleaned, TROUBLESHOOTING, markup_removed=markup_removed)
