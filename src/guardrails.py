"""Risky-action detection: warn when the user asks whether to *perform* a disruptive operation.

The previous version matched any word form (drop\\w*, disable\\w*, ...). Symptom descriptions such as
"approval rate dropped" got a warning, while "should I bounce the service?" did not.

A warning now needs BOTH:
  1. a disruptive action in its base form ("drop", not "dropped"), its -ing form, or its noun form
     ("is a restart safe?"); and
  2. request context: a proposal cue right before it ("should we", "is it safe to", "planning to",
     "let's"), an imperative at the start of a clause ("delete the old logs"), or - as a broader
     safety net - a question or suggestion that mentions the action ("time to restart?").

Descriptions of symptoms or completed events ("keeps getting dropped", "was killed",
"after the restart") have no request context, so they do not warn.
Verbs that are common in everyday wording (stop, remove, clear, reset, ...) only count when
followed by an operational object ("stop the payment service", not "stop these errors").
"""

import re
from dataclasses import dataclass

from src.error_signatures import strip_error_messages

# Operational objects for verbs that are too common to count on their own.
_MOD = r"(?:(?:the|our|this|that|these|those|all|old|stale|every)\s+)*(?:[\w'-]+\s+)?"
_SERVICE_OBJ = _MOD + r"(?:services?|servers?|database|db|pods?|jobs?|cluster|nodes?|process(?:es)?|instances?|containers?|consumers?|workers?|app|application|api|gateway)\b"
_DATA_OBJ = _MOD + r"(?:files?|logs?|data|records?|rows?|archives?|backups?|tables?|index(?:es)?|cache|queues?|messages?|entries|keys?|tokens?|sessions?|connections?)\b"
_MONEY_OBJ = _MOD + r"(?:transactions?|payments?|charges?|settlements?|refunds?)\b"
_SECRET_OBJ = _MOD + r"(?:keys?|credentials|secrets?|certs?|certificates?|passwords?|tokens?)\b"
_REPLICA_OBJ = _MOD + r"(?:replica|standby|secondary)\b"
# Configuration objects (Phase 3). Up to two modifier words, but not a preposition, so
# "increase the gateway timeout" counts and "increase in timeout errors" does not.
_CONFIG_MOD = r"(?:(?:the|our|this|that|its|their)\s+)?(?:(?!(?:in|of|on|for|to|at|with)\b)[\w'-]+\s+){0,2}?"
_CONFIG_OBJ = _CONFIG_MOD + (r"(?:timeouts?|pool\s+size|connection\s+pool|max_connections|feature\s+flags?|dns\s+records?"
                             r"|config(?:uration)?|settings?|thread\s+pool|retry\s+count|limits?)\b")
_CHANGE = r"increase|decrease|raise|lower|reduce|change|modify|update|bump|tweak|edit"
_CHANGING = r"increasing|decreasing|raising|lowering|reducing|changing|modifying|updating|bumping|tweaking|editing"


@dataclass(frozen=True)
class _Action:
    label: str
    base: str        # base form (also matches the noun where it is identical, e.g. "rollback")
    gerund: str      # -ing form, only used after planning verbs
    noun: str = ""   # noun form used in "is a restart safe?" / "needs a restart"
    needs_object: bool = False  # base pattern already includes a required object ("stop the service")


# Vocabulary: actions listed under "requires_approval" in data/knowledge_base.json plus common
# operational synonyms (bounce, failover, flush, drain, ...).
ACTIONS = [
    _Action("restart", r"restart", r"restarting", r"restart"),
    _Action("reboot", r"reboot", r"rebooting", r"reboot"),
    _Action("bounce", r"bounce", r"bouncing", r"bounce"),
    _Action("recycle", r"recycle", r"recycling"),
    _Action("redeploy", r"re-?deploy", r"re-?deploying", r"re-?deploy(?:ment)?"),
    _Action("failover", r"fail[\s-]?over", r"failing\s+over", r"fail-?over"),
    _Action("switchover", r"switch\s+over", r"switching\s+over", r"switch-?over"),
    _Action("shift traffic", r"(?:switch|shift|move)\s+(?:all\s+)?(?:the\s+)?traffic", r"(?:switching|shifting|moving)\s+(?:all\s+)?(?:the\s+)?traffic", needs_object=True),
    _Action("cutover", r"cut\s*over", r"cutting\s+over", r"cut-?over"),
    _Action("reroute", r"re-?route", r"re-?routing"),
    _Action("roll back", r"roll[\s-]?back", r"rolling\s+back", r"roll-?back"),
    _Action("revert", r"revert", r"reverting"),
    _Action("downgrade", r"downgrade", r"downgrading", r"downgrade"),
    _Action("kill", r"kill", r"killing"),
    _Action("terminate", r"terminate", r"terminating"),
    _Action("shut down", r"shut\s*down", r"shutting\s+down", r"shutdown"),
    _Action("take down", r"take\s+down", r"taking\s+down"),
    _Action("stop", r"stop\s+" + _SERVICE_OBJ, r"stopping\s+" + _SERVICE_OBJ, needs_object=True),
    _Action("delete", r"delete", r"deleting"),
    _Action("drop", r"drop", r"dropping"),
    _Action("truncate", r"truncate", r"truncating"),
    _Action("purge", r"purge", r"purging", r"purge"),
    _Action("wipe", r"wipe", r"wiping"),
    _Action("nuke", r"nuke", r"nuking"),
    _Action("remove", r"remove\s+" + _DATA_OBJ, r"removing\s+" + _DATA_OBJ, needs_object=True),
    _Action("clear", r"clear\s+" + _DATA_OBJ, r"clearing\s+" + _DATA_OBJ, needs_object=True),
    _Action("flush", r"flush", r"flushing", r"flush"),
    _Action("evict", r"evict", r"evicting"),
    _Action("drain", r"drain", r"draining"),
    _Action("disable", r"disable", r"disabling"),
    _Action("turn off", r"turn\s+off", r"turning\s+off"),
    _Action("deactivate", r"deactivate", r"deactivating"),
    _Action("scale down", r"scale\s+(?:down|in)", r"scaling\s+(?:down|in)"),
    _Action("reprocess", r"re-?process", r"re-?processing"),
    _Action("re-run", r"re-?run|re-?trigger", r"re-?running|re-?triggering", r"re-?run"),
    _Action("replay", r"replay", r"replaying"),
    _Action("refund", r"refund", r"refunding"),
    _Action("reverse", r"reverse\s+" + _MONEY_OBJ, r"reversing\s+" + _MONEY_OBJ, needs_object=True),
    _Action("force-approve", r"force[\s-]approve", r"force[\s-]approving"),
    _Action("regenerate", r"regenerate", r"regenerating"),
    _Action("revoke", r"revoke", r"revoking"),
    _Action("rotate", r"rotate\s+" + _SECRET_OBJ, r"rotating\s+" + _SECRET_OBJ, needs_object=True),
    _Action("reset", r"reset\s+(?:" + _SERVICE_OBJ + "|" + _DATA_OBJ + ")", r"resetting\s+(?:" + _SERVICE_OBJ + "|" + _DATA_OBJ + ")", needs_object=True),
    _Action("promote", r"promote\s+" + _REPLICA_OBJ, r"promoting\s+" + _REPLICA_OBJ, needs_object=True),
    _Action("change configuration", rf"(?:{_CHANGE})\s+" + _CONFIG_OBJ, rf"(?:{_CHANGING})\s+" + _CONFIG_OBJ, needs_object=True),
]

_BASE = "|".join(f"(?:{a.base})" for a in ACTIONS)
_BASE_PLAIN = "|".join(f"(?:{a.base})" for a in ACTIONS if not a.needs_object)
_BASE_WITH_OBJECT = "|".join(f"(?:{a.base})" for a in ACTIONS if a.needs_object)
_GERUND = "|".join(f"(?:{a.gerund})" for a in ACTIONS)
_NOUN = "|".join(f"(?:{a.noun})" for a in ACTIONS if a.noun)

# 1. A question or proposal cue directly before the action (a few filler words allowed).
_SUBJECT = r"(?:i|we|you|someone|they|ops|the\s+team)"
_CUES = "|".join([
    rf"(?:should|shall|can|could|may|must|would|might)\s+{_SUBJECT}",
    rf"(?:i|we|you)\s*(?:should|shall|must|can|could|will|'ll|might|need\s+to|have\s+to|want\s+to|plan\s+to|gotta|wanna|gonna)",
    r"(?:i'?m|we'?re|you'?re)\s+gonna",
    rf"(?:do|does|did)\s+{_SUBJECT}\s+(?:need|have|want)\s+to",
    r"(?:is|would|will)\s+it(?:\s+be)?\s+(?:safe|ok|okay|fine|wise|alright|better|possible|allowed|a\s+good\s+idea)\s+to",
    r"(?:want|wants|need|needs|plan|planning|ready|about|allowed|supposed|trying|try|decided|recommended?|advised?)\s+to",
    r"(?:i'?m|i\s+am|we'?re|we\s+are)\s+going\s+to",  # "traffic is going to drop" is a prediction, not a plan
    r"(?:i|we)(?:'d|\s+would)\s+like\s+to",
    r"let'?s|let\s+us",
    rf"how\s+(?:do|can|should|would)\s+{_SUBJECT}",
    r"how\s+to",
    rf"(?:what\s+if|why\s+not|why\s+don'?t)\s+{_SUBJECT}",
    r"why\s+not",  # "why not just reboot the gateway?"
])
_FILLERS = r"(?:\s+(?:just|first|now|also|quickly|immediately|maybe|simply|safely|then|really|actually|go\s+ahead\s+and|try\s+to|try\s+and))*"
_DO_A = r"(?:\s+(?:do|perform|trigger|initiate|run|schedule|attempt)\s+(?:a|an|the))?"
_REQUEST = re.compile(rf"\b(?:{_CUES}){_FILLERS}{_DO_A}\s+(?:{_BASE})\b", re.IGNORECASE)

# 2. Planning verbs followed by the -ing form ("thinking about rolling back").
_GERUND_CUES = r"consider|considering|thinking\s+(?:of|about)|planning\s+on|recommend|suggest|how\s+about|what\s+about|worth|try"
_PLANNING = re.compile(rf"\b(?:{_GERUND_CUES})\s+(?:{_GERUND})\b", re.IGNORECASE)

# Negation shortly before an action: "should we not restart", "does not need a restart".
_NEGATED_BEFORE = re.compile(
    r"\b(?:not|no|never|nobody|without|don'?t|doesn'?t|didn'?t|won'?t|shouldn'?t|mustn'?t)(?:\s+[\w']+){0,2}\s+$",
    re.IGNORECASE,
)


def _is_negated(text: str, start: int) -> bool:
    return bool(_NEGATED_BEFORE.search(text[:start]))


# 3. Noun form judged or requested: "is a restart safe?", "the service needs a restart".
_NOUN_QUESTION = re.compile(
    rf"\b(?:is|are|would|will|does|do)\s+(?:a|an|the)\s+(?:quick\s+|full\s+)?(?:{_NOUN})"
    rf"(?:\s+(?:of|on|for)\s+(?:the\s+)?[\w-]+)?\s+(?:be\s+)?"
    r"(?:safe|ok|okay|fine|needed|required|necessary|recommended|a\s+good\s+idea|help|helpful|enough|fix\s+it)\b"
    rf"|\b(?:need|needs|require|requires|recommend|suggest)\s+(?:a|an)\s+(?:quick\s+|full\s+)?(?:{_NOUN})\b",
    re.IGNORECASE,
)


def _noun_question(text: str):
    """Rule 3, ignoring negated forms ("the service does not need a restart")."""
    return next((m for m in _NOUN_QUESTION.finditer(text) if not _is_negated(text, m.start())), None)

# 4. Imperative at the start of a clause, followed by an object: "delete the old logs".
#    ("Drop in approval rate" and "Restart loop on pods" are noun phrases: no object follows.)
_CLAUSE_START = r"(?:^|[.;!?,:]\s*)(?:(?:please|just|quickly|now|maybe|simply|go\s+ahead\s+and)\s+)*"
_OBJECT_START = (r"(?=\s+(?:the|a|an|all|this|that|these|those|our|my|it|them|every|everything|old|stale|prod|production"
                 r"|primary|replica|db|database|service|server|cache|queue|table|pods?|job|node|cluster|traffic|logs?|files?|keys?)\b"
                 r"|\s*[.!?]*\s*$)")
_IMPERATIVE = re.compile(
    rf"{_CLAUSE_START}(?:(?:{_BASE_PLAIN}){_OBJECT_START}|(?:{_BASE_WITH_OBJECT})(?=\W|$))", re.IGNORECASE
)

# 5. Safety net: an action mentioned inside a question or suggestion ("time to restart?",
#    "is restarting safe?", "maybe a reboot fixes it"). Broader than rules 1-4 on purpose: a missed
#    warning is worse than an extra one. Skipped for:
#      - cause/frequency questions:   "why does it keep restarting?", "how long does a failover take?"
#      - informational questions:     "what is a failover?", "how does a rollback work?"
#        (unless the clause also shows intent: "what is the safest way to restart the primary?")
#      - questions about past events: "did the restart fix it?", "was the failover successful?"
#      - descriptive mentions:        "keeps restarting", "after the restart", "restart count", "drain job"
#      - negated mentions:            "should we not restart?"
#    Requests phrased in any of these forms are still caught by rules 1-4 when they have a clear cue.
_MENTION = re.compile(rf"\b(?:{_BASE}|{_GERUND}|{_NOUN})\b", re.IGNORECASE)
_DESCRIPTIVE_BEFORE = re.compile(
    r"(?:\b(?:keep|keeps|kept|still|been|being|started|stopped)"
    r"|\b(?:after|before|during|since|following|post|until|despite)(?:\s+[\w']+){0,2})\s+$",
    re.IGNORECASE,
)
_DESCRIPTIVE_AFTER = re.compile(
    r"^\s+(?:api|apis|endpoint|status|rate|policy|count|loop|storm|history|events?|reason|limit|button|page|flow"
    r"|jobs?|scripts?|switch|flags?|command|plan|window|runbook|duration)\b",
    re.IGNORECASE,
)
_QUESTION_START = re.compile(r"^\s*(?:what|how|is|are|can|could|should|shall|would|will|do|does|did|may|might|must|any|ok|okay)\b", re.IGNORECASE)
_CAUSE_QUESTION = re.compile(r"^\s*(?:why|when|how\s+often|how\s+long|how\s+many)\b", re.IGNORECASE)
_INFO_QUESTION = re.compile(
    r"^\s*(?:what(?:'s|\s+is|\s+are|\s+does|\s+do)\b|how\s+(?:does|do)\s+(?!i\b|we\b)|(?:can|could|would)\s+you\s+explain\b|explain\b)",
    re.IGNORECASE,
)
_INTENT_IN_INFO = re.compile(r"\b(?:i|we|our|us|should|safe|safest|safely)\b|\b(?:way|ways|steps?|procedure|time)\s+to\b", re.IGNORECASE)
_PAST_EVENT_QUESTION = re.compile(r"^\s*(?:did|was|were|has|have|had)\s+(?!to\b)", re.IGNORECASE)
_SUGGESTION = re.compile(r"\b(?:maybe|perhaps|time\s+to|permission\s+to|what\s+if|what\s+happens\s+if|how\s+about|ok\s+to|fine\s+to)\b", re.IGNORECASE)


def _skip_clause(clause: str) -> bool:
    """Clauses that ask about causes, definitions or past events rather than requesting an action."""
    if _CAUSE_QUESTION.match(clause) or _PAST_EVENT_QUESTION.match(clause):
        return True
    return bool(_INFO_QUESTION.match(clause)) and not _INTENT_IN_INFO.search(clause)


def _question_or_suggestion(text: str):
    """Return the first non-descriptive action mention inside a question/suggestion clause, else None."""
    for clause in re.split(r"[.;!\n]+", text):
        if not clause.strip() or _skip_clause(clause):
            continue
        if not ("?" in clause or _QUESTION_START.match(clause) or _SUGGESTION.search(clause)):
            continue
        for mention in _MENTION.finditer(clause):
            before, after = clause[:mention.start()], clause[mention.end():]
            if _DESCRIPTIVE_BEFORE.search(before) or _DESCRIPTIVE_AFTER.match(after) or _is_negated(clause, mention.start()):
                continue
            return mention
    return None


_RULES = (
    ("request", _REQUEST.search),
    ("planning", _PLANNING.search),
    ("noun_question", _noun_question),
    ("imperative", _IMPERATIVE.search),
    ("question_or_suggestion", _question_or_suggestion),
)
_ACTION_FINDERS = [(a.label, re.compile(rf"\b(?:{a.base}|{a.gerund}{'|' + a.noun if a.noun else ''})\b", re.IGNORECASE)) for a in ACTIONS]


@dataclass(frozen=True)
class RiskAssessment:
    is_risky: bool
    action: str | None = None   # canonical action label, e.g. "restart"
    rule: str | None = None     # which rule fired (for debugging and tests)
    evidence: str | None = None  # the matched text


def assess_risk(query: str) -> RiskAssessment:
    """Return whether the query asks about performing a disruptive operation, and why."""
    # Pasted database error text ("try restarting transaction") describes an event, not a request.
    text = strip_error_messages((query or "").replace("’", "'")).strip()
    for rule, find in _RULES:
        match = find(text)
        if match:
            evidence = match.group(0).strip(" .;!?,:")
            action = next((label for label, finder in _ACTION_FINDERS if finder.search(evidence)), None)
            return RiskAssessment(True, action, rule, evidence)
    return RiskAssessment(False)


def risk_warning_text(assessment: RiskAssessment) -> str | None:
    """User-facing warning, or None when the query is not risky."""
    if not assessment.is_risky:
        return None
    action = f" ({assessment.action})" if assessment.action else ""
    return (f"Your question asks about a potentially disruptive action{action}. Do not perform it on production "
            "without approval; check the 'Requires approval' section and escalate.")
