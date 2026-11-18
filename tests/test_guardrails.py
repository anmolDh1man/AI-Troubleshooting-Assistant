"""Labelled tests for risky-action detection (src/guardrails.py). No model needed.

These sentences were written for this test file; they are not copies of the v2 or v3 evaluation
queries. The v1/v2 eval cases that motivated the redesign are checked separately below.
"""

import pytest

from src.guardrails import assess_risk, risk_warning_text

# Requests, proposals or instructions to perform a disruptive operation -> warn.
RISKY = [
    # different ways of asking for a restart
    "should I restart the payments API?",
    "Can we reboot the DB host tonight?",
    "is it ok to bounce the gateway pods",
    "would a restart help here?",
    "the payment service needs a reboot",
    "thinking of restarting the checkout workers",
    "let's restart it and see",
    # failover / traffic / rollback
    "we're going to fail over to the standby database",
    "should we do a failover to DR?",
    "do we need to roll back the 2.3 release?",
    "thinking about rolling back the config change",
    "Is a rollback of the gateway safe at this hour?",
    "we should shift traffic to the backup data centre",
    # data / cache operations
    "let's purge the CDN cache",
    "Delete the stale pods in the payments namespace",
    "please truncate the audit table",
    "can someone flush the redis cache?",
    "try clearing the message queue",
    "how to remove the old backups from the volume",
    # process / capacity / access
    "how do I kill a stuck settlement process?",
    "I'm planning to scale down the worker pool",
    "would it be safe to disable the fraud check for an hour?",
    "we should drain the node before patching",
    "go ahead and terminate the old instances",
    "can you stop the payment service for maintenance",
    "how to revoke the merchant's API key",
    "is it safe to rotate the signing certificate now",
    "should I promote the replica?",
    # money movement
    "Can I reprocess yesterday's failed transactions?",
    "Should we reverse these duplicate charges?",
    "rerun the settlement job",
    "disk is full, delete old log files from /var/log",
    # Added after the first unseen-phrasing probe exposed misses (questions / suggestions / slang).
    "time to restart?",
    "maybe a quick reboot fixes it",
    "is restarting safe?",
    "nuke the cache",
    "do I have permission to drop tables",
    "restarting the db now, ok?",
    "what happens if I kill the consumer",
    "could someone recycle the app pool?",
    "we might need to flush DNS",
    # Phase 2A.1: requested positives and intent inside "informational-looking" questions.
    "Should we restart the database?",
    "Is it safe to fail over?",
    "I'd like to redeploy the gateway",  # probe-2 miss; added as a regression test on request
    "what is the safest way to restart the primary?",
    "what are the steps to fail over to DR?",
    "how do we roll back the gateway release?",
    "have to restart the db?",
    # Hinglish requests
    "kya main payment service restart kar sakta hoon?",
    "logs delete karna theek rahega?",
]

# Symptoms, completed events, questions about something else -> no warning.
HARMLESS = [
    "card approval rate dropped after 10am",
    "connections are being dropped intermittently",
    "the feature flag is disabled in prod",
    "disabled accounts get 403 errors",
    "pods were evicted by the scheduler during the night",
    "we restarted the gateway an hour ago and errors continue",
    "the database failed over to the replica automatically",
    "a rollback happened at 3am",
    "why does the job keep stopping?",
    "the service keeps restarting every few minutes",
    "Drop in authorization rate since the deploy",
    "Restart loop on the gateway pods",
    "how do I stop these 500 errors?",
    "can you explain why the cache was flushed?",
    "the merchant's key was revoked yesterday",
    "traffic shifted to the secondary region during the outage",
    "logs show 'connection reset by peer'",
    "should I check the restart count of the pods?",
    "is the refund API down?",
    "settlement was reprocessed by the ops team",
    "we can see packets drop on the link",
    "the old logs were deleted by the cleanup job",
    "scaling down happened automatically at night",
    "don't restart the database yet, the team is investigating",
    "what does 'connection pool exhausted' mean?",
    # Added after the first unseen-phrasing probe.
    "traffic is going to drop at midnight as usual",
    "I restarted it and it is still failing",
    "the release was rolled back automatically",
    "auth tokens get revoked after 24h",
    "error rate drops after 5 minutes",
    "killed connections show up in the db log",
    # Phase 2A.1: the 15 false warnings found in the Phase 2A read-only review.
    "what is a failover?",
    "how does a rollback work?",
    "what does purge mean in Kafka?",
    "can you explain what a restart does to open connections?",
    "how do pods restart after OOM?",
    "how to recover after a failover",
    "is the drain job stuck?",
    "should we not restart the database?",
    "the service does not need a restart",
    "did the restart fix it?",
    "did someone delete the logs?",
    "did they roll back the release?",
    "latency still high after the restart?",
    "is latency high after the reboot?",
    "can't connect after the failover, what now?",
    # Phase 2A.1: further negation / informational / completed-action edge cases.
    "has the cache been purged?",
    "were the old pods deleted?",
    "what's a cutover window?",
    "is a rollback plan documented anywhere?",
    "during the failover some payments timed out, is that expected?",
    "we must not drop the settlement table",
    # Hinglish descriptions
    "restart ke baad bhi error aa raha hai",
    "kal raat DB restart hua tha aur ab latency high hai",
]

# Known limitations, recorded so a behaviour change is noticed (strict xfail turns red if they start passing).
KNOWN_LIMITATIONS = [
    pytest.param("kya restart se issue fix hua?", False, id="hinglish-past-question-still-warns"),
    pytest.param("can we not just restart it?", True, id="rhetorical-negated-request-not-caught"),
]


@pytest.mark.parametrize("sentence", RISKY)
def test_risky_requests_warn(sentence):
    result = assess_risk(sentence)
    assert result.is_risky, f"missed: {sentence!r}"
    assert result.action and result.rule and result.evidence


@pytest.mark.parametrize("sentence", HARMLESS)
def test_harmless_sentences_do_not_warn(sentence):
    result = assess_risk(sentence)
    assert not result.is_risky, f"false alarm: {sentence!r} (rule={result.rule}, evidence={result.evidence!r})"


# Evaluation cases that motivated the redesign (v1 and v2 data, not v3).
@pytest.mark.parametrize("case_id, query, expected", [
    ("V37", "can we failover the database to DR to fix the connection errors?", True),
    ("V38", "should I bounce the payment service? it keeps throwing 500s", True),
    ("V39", "let's truncate the logs table, disk is almost full", True),
    ("V40", "approval rate dropped sharply for one issuer bank", False),
    ("V41", "connections keep getting dropped between app and database", False),
    ("V42", "merchant API key was disabled and now calls return 401", False),
    ("E27", "Can I drop the transactions table to fix the database connection errors?", True),
    ("E28", "Should I rollback the latest release? Payment API giving 500s", True),
    ("E29", "Just delete old log files on the prod server, disk is full", True),
])
def test_eval_cases_that_motivated_the_redesign(case_id, query, expected):
    assert assess_risk(query).is_risky is expected, case_id


# Phase 3: informal cues, "why not" without a subject, configuration changes, and pasted error text.
@pytest.mark.parametrize("sentence, expected", [
    ("why not restart it?", True),                                  # was a strict-xfail known limitation
    ("why not just reboot the payment gateway?", True),
    ("we gotta flush the cache before the sale", True),
    ("I wanna kill that session", True),
    ("we're gonna redeploy the gateway tonight", True),
    ("should I increase the gateway timeout to 60 seconds?", True),
    ("can we change the connection pool size on the payments service?", True),
    ("let's update the feature flag for checkout", True),
    ("Lower the retry count on the PSP client", True),
    ("Deadlock found when trying to get lock; try restarting transaction", False),
    ("FATAL: terminating connection due to administrator command", False),
    ("the feature flag was changed by the release team yesterday", False),
    ("Increase in timeout errors since noon", False),
    ("why is it not restarting?", False),
    ("traffic is gonna drop after midnight", False),
    ("the config change last night caused 500s", False),
])
def test_phase3_cues_and_error_text(sentence, expected):
    result = assess_risk(sentence)
    assert result.is_risky is expected, f"{sentence!r} (rule={result.rule}, evidence={result.evidence!r})"


def test_error_text_does_not_hide_a_real_request():
    assert assess_risk("Deadlock found when trying to get lock; try restarting transaction. Can we kill the blocking session?").is_risky


@pytest.mark.parametrize("sentence, action", [
    ("should I increase the gateway timeout?", "change configuration"),
    ("should I bounce the payment service?", "bounce"),
    ("can we failover the database?", "failover"),
    ("do we need to roll back the release?", "roll back"),
    ("is a restart safe?", "restart"),
])
def test_assessment_names_the_action(sentence, action):
    assert assess_risk(sentence).action == action


@pytest.mark.xfail(strict=True, reason="documented limitation of the rule-based detector")
@pytest.mark.parametrize("sentence, expected", KNOWN_LIMITATIONS)
def test_known_limitations(sentence, expected):
    assert assess_risk(sentence).is_risky is expected


def test_warning_text():
    assert risk_warning_text(assess_risk("connections dropped")) is None
    warning = risk_warning_text(assess_risk("should I restart the database?"))
    assert "(restart)" in warning and "approval" in warning


def test_empty_and_curly_apostrophe_input():
    assert not assess_risk("").is_risky
    assert not assess_risk(None).is_risky
    assert assess_risk("let’s purge the queue").is_risky
